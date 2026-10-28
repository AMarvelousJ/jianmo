import math

from fastapi.testclient import TestClient
import pytest

from yard_motion.preview import (REAL_SCALE, create_real_scale_preview_app,
                                 preview_config, real_scale_geometry_config,
                                 real_scale_preview_config)
from yard_motion.reclaim_pilot import ReclaimPilot
from yard_motion.geometry import GeometryCalibration


def test_real_scale_scene_mapping_preserves_original_preview():
    old = {m['machine_id']: m for m in preview_config()['machines']}
    new = {m['machine_id']: m for m in real_scale_preview_config()['machines']}
    assert len(new) == 21
    assert old['RC01']['scene']['scale'] == .455
    assert old['RC01']['scene']['z'] == -192
    for machine_id, machine in new.items():
        track = round((-192 - old[machine_id]['scene']['z']) / 36)
        assert machine['scene']['z'] == -180 - track * 60
        assert machine['scene']['scale'] == REAL_SCALE
    assert new['RC01']['axes']['luff']['minimum'] == -15
    assert new['RC01']['scene']['rest_slew_offset'] == 35
    assert new['RC02']['scene']['rest_slew_offset'] == -35
    pilot = ReclaimPilot(new['RC01']['scene'], REAL_SCALE)
    assert real_scale_geometry_config()['wheel']['swept_radius'] == pilot.cutting_radius
    wheel = GeometryCalibration(real_scale_geometry_config()).wheel_envelope(
        new['RC01']['scene'], -345, 0, 0)['center']
    assert [wheel['x'], wheel['y'], wheel['z']] == pytest.approx(pilot.frame({
        'travel': -345, 'slew': 0, 'luff': 0})[2])


def test_real_scale_backend_matches_unity_measured_wheel_at_rest():
    with TestClient(create_real_scale_preview_app(run_clock=False)) as client:
        config = client.get('/api/machines').json()
        state = client.get('/api/state').json()
        assert config['config_version'] == 'yard-real-scale-preview-v1'
        assert state['config_version'] == config['config_version']
        angle = math.radians(125)
        assert state['reclaim_pilot']['wheel_center'] == pytest.approx([
            -345 + 55 * math.cos(angle), 21.5, -180 - 55 * math.sin(angle)])
        assert math.isclose(33 * REAL_SCALE, 55, abs_tol=1e-10)
        lease = client.post('/api/machines/RC01/control/acquire', json={'client_id': 'scale-test'}).json()
        response = client.post('/api/machines/RC01/commands', json={
            'client_id': 'scale-test', 'token': lease['token'],
            'generation': lease['generation'], 'command_id': 'auto', 'command_seq': 1,
            'kind': 'plan_auto_reclaim', 'payload': {},
        })
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'NOT_CALIBRATED'
