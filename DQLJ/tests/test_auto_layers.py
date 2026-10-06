import time
import pytest
from test_preview_pilot import PilotSession
from test_auto_reclaim import await_plan
from yard_motion.errors import MotionError


def wait_worker(s):
    deadline = time.monotonic()+45
    while s.world.state()['auto_reclaim']['status'] in ('PLANNING_NEXT','PLANNING_LAYER'):
        assert time.monotonic() < deadline
        time.sleep(.02)


def test_two_layers_report_real_coverage_and_cut_only_exposed_lower_coal():
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    before = s.world.state()['reclaim_pilot']
    s.command('plan_auto_reclaim', mode='two_layer_pilot')
    plan = await_plan(s)
    assert plan['scope'] == 'two_layers_bounded'
    assert before['heights'] == s.world.state()['reclaim_pilot']['heights']
    s.command('start_auto_reclaim', plan_id=plan['plan_id'])
    seen = set()
    lower_before = None
    lower_start_volume = None
    for _ in range(1600):
        state = s.run(.5)
        job = state['auto_reclaim']
        seen.add(job['status'])
        if job['status'] in ('PLANNING_NEXT','PLANNING_LAYER'):
            wait_worker(s)
        if job['layer_index'] == 1 and lower_before is None:
            lower_before = state['reclaim_pilot']['heights']
            lower_start_volume = state['reclaim_pilot']['reclaimed_m3']
        if job['status'] in ('RETRACTING','PLANNING_LAYER','CHANGE_LAYER'):
            assert not state['reclaim_pilot']['enabled']
            assert state['reclaim_pilot']['actual_m3_s'] == 0
        if job['status'] in ('COMPLETED','FAILED','BLOCKED'):
            break
    assert job['status'] == 'COMPLETED', job
    assert {'PLANNING_LAYER','CHANGE_LAYER'} <= seen
    assert lower_before is not None
    assert state['reclaim_pilot']['reclaimed_m3'] > lower_start_volume
    report = job['coverage_report']
    assert len(report['layers']) == 2
    top, lower = report['layers']
    assert top['bottom_y'] == lower['top_y']
    assert top['remaining_m3'] > 0
    assert top['status'] == 'PARTIAL'
    assert lower['upper_blocked_cells'] > 0
    assert top['reclaimed_m3'] > 0 and lower['reclaimed_m3'] > 0
    assert top['reclaimed_m3']+lower['reclaimed_m3'] == pytest.approx(job['job_reclaimed_m3'], abs=1e-9)
    pile = state['reclaim_pilot']
    assert sum(layer['remaining_m3'] for layer in report['layers'])+report['below_planned_layers_m3'] == pytest.approx(pile['remaining_m3'],abs=1e-9)
    for old, new in zip(lower_before,pile['heights']):
        if old+pile['grid']['ground'] > lower['top_y']+1e-8:
            assert new == old  # buried lower material cannot erase upper coal
        if new < old:
            assert new+pile['grid']['ground'] >= lower['bottom_y']-1e-9
    assert pile['initial_m3'] == pytest.approx(pile['remaining_m3']+pile['reclaimed_m3'],abs=1e-9)
    assert not state['machines']['RC01']['running']


def test_pause_during_layer_search_freezes_inventory_and_discards_lower_plan():
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim', mode='two_layer_pilot')
    plan = await_plan(s)
    s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    for _ in range(1000):
        state = s.run(.5)
        status = state['auto_reclaim']['status']
        if status == 'PLANNING_LAYER':
            break
        if status == 'PLANNING_NEXT':
            wait_worker(s)
        assert status not in ('COMPLETED','FAILED','BLOCKED'), state['auto_reclaim']
    assert status == 'PLANNING_LAYER'
    s.command('pause_auto_reclaim')
    frozen = s.world.state()
    taken = frozen['reclaim_pilot']['reclaimed_m3']
    time.sleep(.1)
    state = s.run(4)
    assert state['reclaim_pilot']['reclaimed_m3'] == taken
    assert state['auto_reclaim']['job_reclaimed_m3'] == frozen['auto_reclaim']['job_reclaimed_m3']
    assert not state['machines']['RC01']['running']
    assert not state['auto_reclaim']['active']
    report = state['auto_reclaim']['coverage_report']
    assert report['layers'][1]['reclaimed_m3'] == 0
    assert sum(l['remaining_m3'] for l in report['layers'])+report['below_planned_layers_m3'] == pytest.approx(state['reclaim_pilot']['remaining_m3'],abs=1e-9)
    with pytest.raises(MotionError, match='重新生成计划'):
        s.command('start_auto_reclaim', plan_id=frozen['auto_reclaim']['plan']['plan_id'])
    # Existing manual pilot can still operate after takeover. Its debit must
    # change current stock, but cannot rewrite this stopped task's settlement.
    s.command('set_wheel',speed=6)
    s.command('set_belt',speed=2)
    s.command('set_reclaim_pilot',enabled=True)
    s.command('set_targets',targets={'slew':0,'luff':-8})
    state=s.run(20)
    assert state['reclaim_pilot']['reclaimed_m3'] > taken
    assert state['auto_reclaim']['coverage_report'] == report
    assert state['auto_reclaim']['job_reclaimed_m3'] == frozen['auto_reclaim']['job_reclaimed_m3']


def test_immediate_pause_freezes_a_complete_inventory_partition():
    s=PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim',mode='two_layer_pilot')
    plan=await_plan(s)
    s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    s.command('pause_auto_reclaim')
    state=s.world.state()
    report=state['auto_reclaim']['coverage_report']
    assert report['settled']
    assert report['remaining_m3'] == pytest.approx(346)
    assert report['material_version'] == state['reclaim_pilot']['material_version']
    assert sum(l['remaining_m3'] for l in report['layers'])+report['below_planned_layers_m3'] == pytest.approx(346)
