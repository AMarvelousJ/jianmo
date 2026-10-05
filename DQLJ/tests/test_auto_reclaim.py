import pytest
import time
from test_preview_pilot import PilotSession
from yard_motion.errors import MotionError


def await_plan(session):
    deadline = time.monotonic()+30
    while session.world.state()['auto_reclaim']['status'] == 'PLANNING':
        assert time.monotonic() < deadline
        time.sleep(.02)
    job = session.world.state()['auto_reclaim']
    assert job['status'] == 'PLANNED', job
    return job['plan']


def test_plan_is_read_only_and_one_automatic_sweep_reclaims_real_volume():
    session = PilotSession()
    session.command('reset_reclaim_pilot')
    before = session.world.state()
    session.command('plan_auto_reclaim')
    await_plan(session)
    planned = session.world.state()
    assert planned['machines']['RC01']['axes'] == before['machines']['RC01']['axes']
    assert planned['reclaim_pilot']['heights'] == before['reclaim_pilot']['heights']
    plan = planned['auto_reclaim']['plan']
    assert plan['scope'] == 'single_top_layer_strip'
    session.command('start_auto_reclaim', plan_id=plan['plan_id'])
    seen = set()
    for _ in range(360):
        state = session.run(.5)
        job = state['auto_reclaim']
        seen.add(job['status'])
        if job['status'] in ('COMPLETED', 'BLOCKED', 'FAILED'):
            break
    assert job['status'] == 'COMPLETED', job
    assert 'SWEEPING' in seen
    assert job['job_reclaimed_m3'] > .001
    pile = state['reclaim_pilot']
    assert pile['initial_m3'] == pytest.approx(pile['remaining_m3'] + pile['reclaimed_m3'], abs=1e-9)
    assert pile['remaining_m3'] > 0
    assert job['reason'] == 'SINGLE_STRIP_COMPLETE'
    assert job['exit_classification'] in ('MODEL_CLEAR', 'GEOMETRY_LIMIT', 'PLANNED_LIMIT')
    if job['edge_confirmed']:
        assert job['exit_classification'] == 'MODEL_CLEAR'
        assert job['continuous_no_flow_s'] >= 1.0
    floor = plan['layer_bottom_y'] - pile['grid']['ground']
    for old, new in zip(before['reclaim_pilot']['heights'], pile['heights']):
        if new < old:
            assert new >= floor - 1e-9
    assert not state['machines']['RC01']['running']


@pytest.mark.parametrize('kind,payload', [('set_wheel',{'speed':0}),('set_belt',{'speed':0}),
    ('estop',{}),('stop',{}),('pause_auto_reclaim',{}),('take_manual_control',{}),('cancel_auto_reclaim',{})])
def test_auto_stops_debit_on_every_stop_and_requires_explicit_new_plan(kind, payload):
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim')
    plan = await_plan(s)
    s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    for _ in range(170):
        state = s.run(.5)
        if state['auto_reclaim']['job_reclaimed_m3'] > .001:
            break
    assert state['auto_reclaim']['job_reclaimed_m3'] > .001
    with pytest.raises(MotionError,match='自动任务'):
        s.command('set_targets',targets={'slew':20})
    s.command(kind,**payload)
    taken = s.world.state()['reclaim_pilot']['reclaimed_m3']
    state = s.run(4)
    assert state['reclaim_pilot']['reclaimed_m3'] == taken
    assert not state['auto_reclaim']['active']
    assert state['auto_reclaim']['job_reclaimed_m3'] == taken
    if kind == 'estop':
        s.command('clear_estop')
    s.command('set_wheel',speed=6)
    s.command('set_belt',speed=2)
    state = s.run(2)
    assert not state['auto_reclaim']['active']
    assert state['reclaim_pilot']['reclaimed_m3'] == taken


def test_old_pose_plan_is_rejected_and_repeated_start_does_not_create_another_job():
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim')
    plan = await_plan(s)
    s.command('set_targets',targets={'luff':1})
    s.run(4)
    with pytest.raises(MotionError,match='姿态已变化'):
        s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    s.command('plan_auto_reclaim')
    plan = await_plan(s)
    result = s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    job = s.world.state()['auto_reclaim']['job_id']
    repeated = s.world.command('RC01','pilot',s.lease['token'],s.lease['generation'],str(s.seq),s.seq,
                              'start_auto_reclaim',{'plan_id':plan['plan_id']})
    assert repeated == result
    assert s.world.state()['auto_reclaim']['job_id'] == job
    s.now = 4
    state = s.world.state()
    assert state['auto_reclaim']['status'] == 'CONTROL_LOST'
    assert not state['reclaim_pilot']['enabled']
    assert s.run(4)['reclaim_pilot']['reclaimed_m3'] == 0


def test_immediate_pause_requires_replanning_even_without_pose_or_material_change():
    s=PilotSession()
    s.command('reset_reclaim_pilot')
    s.command('plan_auto_reclaim')
    plan=await_plan(s)
    s.command('start_auto_reclaim',plan_id=plan['plan_id'])
    s.command('pause_auto_reclaim')
    with pytest.raises(MotionError,match='重新生成计划'):
        s.command('start_auto_reclaim',plan_id=plan['plan_id'])


def test_planning_http_is_nonblocking_heartbeats_remain_available_and_reset_invalidates_plan():
    from fastapi.testclient import TestClient
    from yard_motion.preview import create_preview_app
    s = PilotSession()
    s.command('reset_reclaim_pilot')
    with TestClient(create_preview_app(world=s.world,run_clock=False)) as client:
        body=dict(client_id='pilot',token=s.lease['token'],generation=s.lease['generation'])
        started=time.monotonic()
        response=client.post('/api/machines/RC01/commands',json=dict(body,command_id='http-plan',
                             command_seq=1,kind='plan_auto_reclaim',payload={}))
        # reset already consumed sequence 1.
        assert response.status_code == 409
        response=client.post('/api/machines/RC01/commands',json=dict(body,command_id='http-plan',
                             command_seq=2,kind='plan_auto_reclaim',payload={}))
        assert response.status_code == 200
        assert time.monotonic()-started < 1.0
        assert client.put('/api/machines/RC01/control/heartbeat',json=body).status_code == 200
        assert client.get('/api/state').status_code == 200
        s.seq=2
        plan=await_plan(s)
        s.command('reset_reclaim_pilot')
        with pytest.raises(MotionError,match='有效计划'):
            s.command('start_auto_reclaim',plan_id=plan['plan_id'])
