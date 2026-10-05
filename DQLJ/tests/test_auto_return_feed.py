import time
import pytest
from yard_motion.errors import MotionError
from yard_motion.preview import preview_config
from yard_motion.reclaim_pilot import PreviewWorld
from test_auto_reclaim import await_plan
from test_preview_pilot import PilotSession


def test_two_strips_reverse_after_safe_feed_without_debit_between_strips():
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim', mode='two_strip_return')
    plan = await_plan(s)
    assert plan['scope'] == 'two_top_layer_strips'
    s.command('start_auto_reclaim', plan_id=plan['plan_id'])
    seen = set()
    first = None
    for _ in range(720):
        state = s.run(.5)
        job = state['auto_reclaim']
        seen.add(job['status'])
        if job['status'] == 'SWEEPING' and not job['completed_strips']:
            assert state['machines']['RC01']['axes']['travel']['position'] == pytest.approx(plan['travel'])
        if job['status'] == 'PLANNING_NEXT':
            deadline = time.monotonic()+30
            while job['status'] == 'PLANNING_NEXT':
                assert time.monotonic() < deadline
                time.sleep(.02)
                job = s.world.state()['auto_reclaim']
        if job['completed_strips']:
            first = job['completed_strips'][0]
        if job['status'] in ('STRIP_STOPPING', 'RETRACTING', 'PLANNING_NEXT', 'FEEDING'):
            assert not state['reclaim_pilot']['enabled']
            assert state['reclaim_pilot']['actual_m3_s'] == 0
            assert state['reclaim_pilot']['reclaimed_m3'] == pytest.approx(first['end_reclaimed_m3'])
        if job['status'] in ('COMPLETED', 'BLOCKED', 'FAILED'):
            break
    assert job['status'] == 'COMPLETED', job
    assert {'STRIP_STOPPING', 'RETRACTING', 'PLANNING_NEXT', 'FEEDING'} <= seen
    strips = job['completed_strips']
    assert len(strips) == 2
    assert strips[0]['slew_end'] > strips[0]['slew_start']
    assert strips[1]['slew_end'] < strips[1]['slew_start']
    assert .0249 <= abs(strips[1]['travel']-strips[0]['travel']) <= .1001
    assert strips[0]['layer_bottom_y'] == strips[1]['layer_bottom_y']
    assert strips[1]['end_reclaimed_m3'] > strips[0]['end_reclaimed_m3'] > .001
    assert job['reason'] == 'TWO_STRIPS_COMPLETE'
    pile = state['reclaim_pilot']
    assert pile['initial_m3'] == pytest.approx(pile['remaining_m3']+pile['reclaimed_m3'], abs=1e-9)
    assert pile['remaining_m3'] > 0
    assert not state['machines']['RC01']['running']


@pytest.mark.parametrize('phase,stop', [('PLANNING_NEXT','cancel_auto_reclaim'), ('FEEDING','estop')])
def test_stop_during_next_plan_or_feed_discards_future_and_never_resumes(phase, stop):
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim', mode='two_strip_return')
    plan = await_plan(s)
    s.command('start_auto_reclaim', plan_id=plan['plan_id'])
    for _ in range(8000):
        state = s.run(.02)
        status = state['auto_reclaim']['status']
        if status == phase:
            break
        if status == 'PLANNING_NEXT':
            time.sleep(.02)
        assert status not in ('FAILED','BLOCKED','COMPLETED'), state['auto_reclaim']
    assert status == phase
    s.command(stop)
    taken = s.world.state()['reclaim_pilot']['reclaimed_m3']
    # Let a cancelled worker finish; its result must not write an axis target.
    time.sleep(.1)
    state = s.run(4)
    assert not state['auto_reclaim']['active']
    assert state['reclaim_pilot']['reclaimed_m3'] == taken
    assert len(state['auto_reclaim']['completed_strips']) == 1
    assert not state['machines']['RC01']['running']
    if stop == 'estop':
        s.command('clear_estop')
    with pytest.raises(MotionError, match='重新生成计划'):
        s.command('start_auto_reclaim', plan_id=state['auto_reclaim']['plan']['plan_id'])
    assert s.run(2)['reclaim_pilot']['reclaimed_m3'] == taken


def test_all_feed_candidates_outside_configured_track_limits_stop_without_second_strip():
    # Public world construction with narrower TEST limits, not a mocked guard
    # or changes to production machinery. Initial pose is already safely raised.
    config = preview_config()
    rc = next(m for m in config['machines'] if m['machine_id'] == 'RC01')
    rc['axes']['travel'].update(initial=-328., minimum=-328.01, maximum=-327.99)
    rc['axes']['luff']['initial'] = 15.
    s = PilotSession()
    s.world = PreviewWorld(config, clock=lambda:s.now)
    s.lease = s.world.acquire('RC01','pilot')
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim', mode='two_strip_return')
    plan = await_plan(s)
    s.command('start_auto_reclaim', plan_id=plan['plan_id'])
    for _ in range(300):
        state = s.run(.5)
        job = state['auto_reclaim']
        if job['status'] == 'PLANNING_NEXT':
            time.sleep(.02)
        if job['status'] in ('BLOCKED','FAILED','COMPLETED'):
            break
    assert job['status'] == 'BLOCKED'
    assert job['reason'] == 'NO_SAFE_FEED'
    assert len(job['completed_strips']) == 1
    assert state['machines']['RC01']['axes']['travel']['position'] == pytest.approx(plan['travel'])
    taken = state['reclaim_pilot']['reclaimed_m3']
    assert not state['reclaim_pilot']['enabled']
    assert not state['machines']['RC01']['running']
    assert s.run(2)['reclaim_pilot']['reclaimed_m3'] == taken
