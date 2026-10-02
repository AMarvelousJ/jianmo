import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yard_motion.api import create_app
from yard_motion.errors import MotionError
from yard_motion.material import MaterialDomain
from yard_motion.world import World

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/material.json"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_init_empty_reports_zero_inventory():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    state = domain.state()
    assert state["scene"] == "empty"
    inventory = state["inventory"]
    assert inventory["in_zone_m3"] == 0
    assert inventory["spilled_m3"] == 0
    assert inventory["total_m3"] == 0
    ledger = state["ledger"]
    assert ledger["initial_m3"] == 0
    assert ledger["received_m3"] == 0
    assert ledger["output_m3"] == 0
    assert state["version"] >= 1


def test_init_preset_records_initial_stock_and_conservation():
    domain = MaterialDomain(load_config())
    domain.init_scene("preset")
    state = domain.state()
    assert state["scene"] == "preset"
    inventory, ledger = state["inventory"], state["ledger"]
    assert inventory["in_zone_m3"] > 0
    assert inventory["spilled_m3"] == 0
    assert inventory["total_m3"] == pytest.approx(inventory["in_zone_m3"], abs=1e-9)
    assert ledger["initial_m3"] == pytest.approx(inventory["total_m3"], abs=1e-9)
    identity = ledger["initial_m3"] + ledger["received_m3"] - ledger["output_m3"] - inventory["total_m3"]
    assert abs(identity) <= 1e-8
    density = load_config()["coal"]["density_t_per_m3"]
    assert inventory["total_t"] == pytest.approx(inventory["total_m3"] * density, rel=1e-12)
    assert inventory["in_zone_t"] == pytest.approx(inventory["in_zone_m3"] * density, rel=1e-12)


def conservation_error(state):
    ledger, inventory = state["ledger"], state["inventory"]
    processed = ledger["initial_m3"] + ledger["received_m3"] + ledger["output_m3"]
    tolerance = max(1e-8, processed * 1e-9)
    identity = ledger["initial_m3"] + ledger["received_m3"] - ledger["output_m3"] - inventory["total_m3"]
    return abs(identity), tolerance


def test_deposit_and_remove_conserve_volume():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    for k in range(20):
        result = domain.deposit(-560.0 + k * 5.0, -210.0, 10.0)
        assert result["accepted_m3"] == pytest.approx(10.0, abs=1e-9)
    state = domain.state()
    assert state["inventory"]["in_zone_m3"] == pytest.approx(200.0, abs=1e-9)
    bounded = domain.remove(-510.0, -210.0, 4.5, 20.0)
    assert 0 < bounded < 20.0
    emptied = domain.remove(-510.0, -210.0, 4.5, 20.0)
    assert emptied == pytest.approx(0.0, abs=1e-12)
    state = domain.state()
    assert state["ledger"]["output_m3"] == pytest.approx(bounded, abs=1e-9)
    assert state["inventory"]["in_zone_m3"] == pytest.approx(200.0 - bounded, abs=1e-9)
    assert state["inventory"]["spilled_m3"] == 0
    error, tolerance = conservation_error(state)
    assert error <= tolerance


def test_remove_returns_requested_amount_when_available():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    for k in range(20):
        domain.deposit(-560.0 + k * 5.0, -210.0, 10.0)
    removed = domain.remove(-510.0, -210.0, 9.0, 20.0)
    assert removed == pytest.approx(20.0, abs=1e-9)
    state = domain.state()
    assert state["ledger"]["output_m3"] == pytest.approx(20.0, abs=1e-9)
    assert state["inventory"]["in_zone_m3"] == pytest.approx(180.0, abs=1e-9)
    error, tolerance = conservation_error(state)
    assert error <= tolerance


def test_deposit_near_edge_classifies_spill():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    result = domain.deposit(-510.0, -196.0, 10.0)
    assert result["accepted_m3"] == pytest.approx(10.0, abs=1e-9)
    state = domain.state()
    assert state["inventory"]["spilled_m3"] > 0
    assert state["inventory"]["in_zone_m3"] > 0
    error, tolerance = conservation_error(state)
    assert error <= tolerance


def test_deposit_outside_domain_is_refused():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    with pytest.raises(MotionError) as info:
        domain.deposit(-100.0, -210.0, 10.0)
    assert info.value.code == "MATERIAL_OUT_OF_DOMAIN"
    state = domain.state()
    assert state["ledger"]["received_m3"] == 0
    assert state["inventory"]["total_m3"] == 0


def test_deposit_before_scene_init_is_refused():
    domain = MaterialDomain(load_config())
    with pytest.raises(MotionError) as info:
        domain.deposit(-510.0, -210.0, 10.0)
    assert info.value.code == "MATERIAL_UNINITIALIZED"


def test_deposit_rejects_when_pile_reaches_height_limit():
    domain = MaterialDomain(load_config())
    domain.init_scene("empty")
    accepted_total = 0.0
    result = None
    for _ in range(500):
        result = domain.deposit(-510.0, -210.0, 5.0)
        accepted_total += result["accepted_m3"]
    limit = load_config()["coal"]["max_height"]
    assert result["reason"] == "RECEIVE_LIMITED"
    # the kernel window saturates well below the requested 2500 m3 and respects the hard cap
    assert 150.0 < accepted_total <= 200.0 + 1e-9
    assert max(domain.heights) <= limit + 1e-9
    state = domain.state()
    # refused volume is not counted as input: ledger and inventory agree
    assert state["ledger"]["received_m3"] == pytest.approx(accepted_total, abs=1e-9)
    assert state["inventory"]["total_m3"] == pytest.approx(accepted_total, abs=1e-9)
    error, tolerance = conservation_error(state)
    assert error <= tolerance


def test_heights_stay_nonnegative_and_ground_is_separate():
    domain = MaterialDomain(load_config())
    domain.init_scene("preset")
    ground_before = list(domain.ground)
    for _ in range(50):
        domain.deposit(-510.0, -196.0, 2.0)
        domain.remove(-365.0, -210.0, 3.0, 1.0)
    assert min(domain.heights) >= 0
    assert max(domain.heights) <= load_config()["coal"]["max_height"] + 1e-9
    assert domain.ground == ground_before
    error, tolerance = conservation_error(domain.state())
    assert error <= tolerance


def test_grid_resolution_is_configurable():
    nominal = MaterialDomain(load_config())
    nominal.init_scene("preset")
    nominal_volume = nominal.state()["ledger"]["initial_m3"]
    assert nominal_volume > 0
    for cell_size, cells_x, cells_z in ((0.25, 2040, 200), (1.0, 510, 50)):
        config = load_config()
        config["grid"] = {"cell_size": cell_size, "origin_x": -665.0, "origin_z": -235.0,
                          "cells_x": cells_x, "cells_z": cells_z}
        domain = MaterialDomain(config)
        domain.init_scene("preset")
        volume = domain.state()["ledger"]["initial_m3"]
        tolerance = 0.05 if cell_size == 1.0 else 0.02
        assert abs(volume - nominal_volume) / nominal_volume < tolerance
        domain.init_scene("empty")
        accepted = domain.deposit(-510.0, -210.0, 10.0)["accepted_m3"]
        assert accepted == pytest.approx(10.0, abs=1e-9)
        error, _ = conservation_error(domain.state())
        assert error <= max(1e-8, (10.0) * 1e-9)


def test_preset_extending_past_spill_zone_is_clipped_and_conserved():
    config = load_config()
    config["preset"] = dict(config["preset"], center_z=-190.0)  # tail reaches past the spill boundary
    domain = MaterialDomain(config)
    domain.init_scene("preset")
    state = domain.state()
    assert state["ledger"]["initial_m3"] > 0
    assert state["inventory"]["spilled_m3"] > 0
    # every cell carrying coal is accounted: grid volume equals ledger inventory
    grid_volume = sum(domain.heights) * domain.cell * domain.cell
    assert grid_volume == pytest.approx(state["inventory"]["total_m3"], abs=1e-6)
    # nothing was placed outside the spill zone, so nothing can be reclaimed there
    assert domain.remove(-365.0, -185.0, 1.5, 10.0) == pytest.approx(0.0, abs=1e-12)
    error, tolerance = conservation_error(domain.state())
    assert error <= tolerance


def test_world_state_includes_material_section():
    world = World()
    world.init_material("preset")
    material = world.state()["material"]
    assert material["scene"] == "preset"
    assert material["ledger"]["initial_m3"] > 0
    assert material["inventory"]["total_m3"] == pytest.approx(material["ledger"]["initial_m3"], abs=1e-9)
    assert material["version"] >= 1


def test_world_reinit_nonempty_scene_requires_confirmation():
    world = World()
    world.init_material("preset")
    with pytest.raises(MotionError) as info:
        world.init_material("empty")
    assert info.value.code == "CONFIRM_REQUIRED"
    world.init_material("empty", confirm=True)
    material = world.state()["material"]
    assert material["scene"] == "empty"
    assert material["inventory"]["total_m3"] == 0


def test_api_material_scene_state_and_config():
    from test_material_control import scene_controls

    world = World(clock=lambda: 0.0)
    client = TestClient(create_app(world, run_clock=False))
    credentials = scene_controls(world)
    response = client.post("/api/material/scene", json=dict(credentials, command_id="init", command_seq=1, mode="preset"))
    assert response.status_code == 200
    assert response.json()["scene"] == "preset"
    state = client.get("/api/state").json()
    assert state["material"]["inventory"]["total_m3"] > 0
    config = client.get("/api/material/config").json()
    assert config["version"] == "coal-material-demo-v2"
    assert config["demo"] is True
    assert config["source"]
    assert config["calibration"]["version"]
    assert config["zones"]["yard"]["x"] == [-655.0, -165.0]
    assert config["zones"]["yard"]["z"] == [-225.0, -195.0]
    assert config["zones"]["spill"]["x"] == [-663.0, -157.0]
    assert config["grid"]["cell_size"] == 0.5
    assert config["ground"]["elevation"] == 0.0
    assert config["coal"]["density_t_per_m3"] == 0.85
    assert config["coal"]["repose_angle_deg"] == 35.0
    assert config["coal"]["max_height"] == 8.0
    assert config["coal"]["flow_capability_t_per_h"] == 3000.0
    assert "token" not in json.dumps(config)
    assert "lease" not in json.dumps(config)
    refused = client.post("/api/material/scene", json=dict(credentials, command_id="unconfirmed", command_seq=2, mode="empty"))
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "CONFIRM_REQUIRED"
    confirmed = client.post("/api/material/scene", json=dict(credentials, command_id="reset", command_seq=2, mode="empty", confirm=True))
    assert confirmed.status_code == 200
    assert client.get("/api/state").json()["material"]["inventory"]["total_m3"] == 0
    unknown = client.post("/api/material/scene", json=dict(credentials, command_id="unknown", command_seq=3, mode="nonsense", confirm=True))
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "INVALID_SCENE"
