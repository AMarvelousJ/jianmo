import pytest
from fastapi.testclient import TestClient
from yard_motion.preview import create_preview_app
from yard_motion.preview import preview_config
from yard_motion.reclaim_pilot import PreviewWorld


class PilotSession:
    def __init__(self):
        self.now = 0
        self.world = PreviewWorld(preview_config(), clock=lambda:self.now)
        self.lease = self.world.acquire('RC01','pilot')
        self.seq = 0

    def command(self, kind, **payload):
        self.seq += 1
        return self.world.command('RC01','pilot',self.lease['token'],self.lease['generation'],
                                  str(self.seq),self.seq,kind,payload)

    def run(self, seconds):
        for _ in range(round(seconds/.02)):
            self.world.advance(.02)
        return self.world.state()

    def prepare(self):
        self.command('reset_reclaim_pilot')
        self.command('set_targets', targets={'luff':-8})
        self.run(7)


def test_rc01_pilot_requires_control_and_exposes_only_cubic_metres():
    with TestClient(create_preview_app()) as client:
        state = client.get('/api/state').json()
        assert state['reclaim_pilot']['version'] == 'rc01-coal-pilot-v1'
        assert not state['reclaim_pilot']['initialized']
        response = client.post('/api/machines/RC01/commands', json=dict(
            client_id='pilot', token='invalid', generation=1, command_id='reset', command_seq=1,
            kind='reset_reclaim_pilot', payload={}))
        assert response.status_code == 403
        lease = client.post('/api/machines/RC01/control/acquire', json={'client_id':'pilot'}).json()
        response = client.post('/api/machines/RC01/commands', json=dict(
            client_id='pilot',token=lease['token'],generation=lease['generation'],command_id='reset',command_seq=1,
            kind='reset_reclaim_pilot',payload={}))
        assert response.status_code == 200
        pile = client.get('/api/state').json()['reclaim_pilot']
        assert pile['initialized'] and pile['remaining_m3'] > 0
        assert pile['reclaimed_m3'] == 0
        assert not any('_t' in k for k in pile)


def test_disabled_pilot_blocks_travel_into_coal_and_allows_retreat_without_debit():
    session = PilotSession()
    session.prepare()
    session.command('set_targets',targets={'travel':-328})
    state = session.run(15)
    assert state['reclaim_pilot']['blocked']
    assert state['machines']['RC01']['axes']['travel']['position'] < -333
    assert state['reclaim_pilot']['reclaimed_m3'] == 0
    session.command('set_targets',targets={'travel':-345})
    state = session.run(12)
    assert state['machines']['RC01']['axes']['travel']['position'] == pytest.approx(-345)
    assert not state['reclaim_pilot']['blocked']


def test_cutting_at_guard_debits_volume_and_stop_command_prevents_further_debit():
    session = PilotSession()
    session.command('reset_reclaim_pilot')
    session.command('set_targets',targets={'luff':15})
    session.run(10)
    session.command('set_targets',targets={'travel':-328})
    session.run(14)
    session.command('set_reclaim_pilot',enabled=True)
    session.command('set_wheel',speed=6)
    session.command('set_belt',speed=2)
    session.command('set_targets',targets={'luff':-8})
    state = session.run(18)
    pile = state['reclaim_pilot']
    assert pile['reclaimed_m3'] > .001
    assert pile['initial_m3'] == pytest.approx(pile['remaining_m3']+pile['reclaimed_m3'],abs=1e-9)
    assert min(pile['heights']) >= 0
    session.command('set_wheel',speed=0)
    state = session.run(4)
    assert state['reclaim_pilot']['reclaimed_m3'] == pile['reclaimed_m3']
    assert state['reclaim_pilot']['actual_m3_s'] == 0
    # Restarting a drive alone must not resume material integration.
    session.command('set_wheel',speed=6)
    state = session.run(3)
    assert not state['reclaim_pilot']['enabled']
    assert state['reclaim_pilot']['reclaimed_m3'] == pile['reclaimed_m3']
    for kind,payload in [('set_belt',{'speed':0}),('estop',{})]:
        session.command('set_belt',speed=2)
        session.command('set_reclaim_pilot',enabled=True)
        session.run(1)
        session.command(kind,**payload)
        stopped = session.world.state()['reclaim_pilot']['reclaimed_m3']
        assert session.run(3)['reclaim_pilot']['reclaimed_m3'] == stopped
        assert not session.world.state()['reclaim_pilot']['enabled']
    session.command('clear_estop')
    # Restore is refused while the original pile would intersect the wheel.
    session.command('stop')
    session.run(5)
    from yard_motion.errors import MotionError
    with pytest.raises(MotionError,match='恢复位置'):
        session.command('reset_reclaim_pilot')
    session.command('set_targets',targets={'luff':15})
    session.run(14)
    session.command('reset_reclaim_pilot')
    reset = session.world.state()['reclaim_pilot']
    assert reset['reclaimed_m3'] == 0
    assert reset['remaining_m3'] == reset['initial_m3']
    session.command('set_reclaim_pilot',enabled=True)
    session.now = 4
    assert not session.world.state()['reclaim_pilot']['enabled']


def test_geometry_matches_recorded_unity_centres_and_other_machines_unchanged():
    session = PilotSession()
    fixtures = [(-8,[-345,3.77826571,-206.891037]),(0,[-345,5.8695,-207.015]),
                (15,[-345,9.750242,-206.462158])]
    for luff,center in fixtures:
        session.command('set_targets',targets={'luff':luff})
        state = session.run(16)
        assert state['reclaim_pilot']['wheel_center'] == pytest.approx(center,abs=.00005)
        assert state['machines']['RC02']['axes']['travel']['position'] == -290
        assert not state['material']['scene'] == 'preset'


def test_reset_uses_safe_path_and_zero_length_steps_do_not_cut():
    session = PilotSession()
    session.prepare()
    state = session.world.state()
    session.world.advance(0)
    assert session.world.state()['reclaim_pilot'] == state['reclaim_pilot']
    session.command('set_targets',targets={'slew':90})
    session.run(23)
    # Reset is allowed when the entire return path stays outside the test pile.
    session.command('reset')
    assert session.world.state()['machines']['RC01']['axes']['slew']['position'] == 0


def test_guard_allows_luff_retreat_while_an_inward_travel_target_remains():
    session = PilotSession()
    session.prepare()
    session.command('set_targets',targets={'travel':-328})
    state = session.run(15)
    assert state['reclaim_pilot']['blocked']
    session.command('set_targets',targets={'luff':15})
    state = session.run(16)
    assert state['machines']['RC01']['axes']['luff']['position'] == pytest.approx(15)
    assert state['reclaim_pilot']['reclaimed_m3'] == 0
