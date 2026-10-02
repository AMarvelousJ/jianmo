import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yard_motion.api import create_app
from yard_motion.world import World
from test_stacking import Operator, START_PAYLOAD


def test_grid_snapshot_exposes_classified_shape_and_is_detached():
    world = World(clock=lambda: 0.0)
    world.init_material("preset")
    with TestClient(create_app(world, run_clock=False)) as client:
        response = client.get("/api/material/grid")
    assert response.status_code == 200
    snapshot = response.json()
    grid = snapshot["grid"]
    assert len(grid["coal_thickness_m"]) == grid["cells_x"] * grid["cells_z"]
    assert len(grid["ground_elevation_m"]) == len(grid["zone_codes"]) == len(grid["coal_thickness_m"])
    assert snapshot["material"]["inventory"]["total_m3"] > 0
    assert snapshot["server_instance_id"] == world.state()["server_instance_id"]
    detached = world.material_grid()
    detached["grid"]["coal_thickness_m"][0] = 99
    assert world.material_grid()["grid"]["coal_thickness_m"][0] == 0


def test_reachable_spill_is_reclaimed_and_classification_tracks_current_stock():
    config = json.loads((Path(__file__).parents[1] / "config/material.json").read_text(encoding="utf-8"))
    # A configured spill-only pile below the real RC01 wheel; no geometry scaling.
    config["preset"].update(center_x=-360, center_z=-191, length_x=20,
                            base_width_z=6, top_width_z=2, height=4)
    world = World(clock=lambda: 0.0, material_config=config)
    world.init_material("preset")
    initial = world.material_grid()["material"]["inventory"]
    assert initial["in_zone_m3"] == 0
    assert initial["spilled_m3"] > 0
    op = Operator(world, "RC01")
    op.settle({"travel": -345, "slew": 0, "luff": -8})
    op.send("set_wheel", {"speed": 8})
    op.send("set_belt", {"speed": 4})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", START_PAYLOAD)
    for _ in range(100):
        world.advance(.1)
    snapshot = world.material_grid()
    material, grid = snapshot["material"], snapshot["grid"]
    assert material["ledger"]["output_m3"] > 0
    assert material["inventory"]["spilled_m3"] < initial["spilled_m3"]
    area = grid["cell_size"] ** 2
    for code, key in ((1, "spilled_m3"), (2, "in_zone_m3")):
        rendered_volume = sum(h * area for h, zone in zip(grid["coal_thickness_m"], grid["zone_codes"]) if zone == code)
        assert material["inventory"][key] == pytest.approx(rendered_volume, abs=1e-8)
    assert material["inventory"]["total_m3"] + material["ledger"]["output_m3"] == pytest.approx(initial["total_m3"], abs=1e-8)
    assert min(grid["coal_thickness_m"]) >= 0
    # Reads must not accumulate the same spill a second time.
    assert world.material_grid()["material"] == material


def test_boundary_stacking_keeps_spill_visible_during_slope_relaxation():
    world = World(clock=lambda: 0.0)
    world.init_material("empty")
    op = Operator(world, "ST01")
    op.settle({"travel": -500, "slew": 12, "luff": 0})
    op.send("set_belt", {"speed": 4})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", START_PAYLOAD)
    for _ in range(50):
        world.advance(.1)
    op.send("pause_job")
    received = world.state()["material"]["ledger"]["received_m3"]
    assert received > 0
    for _ in range(100):
        world.advance(.1)
    snapshot = world.material_grid()
    grid, material = snapshot["grid"], snapshot["material"]
    inventory = material["inventory"]
    assert inventory["spilled_m3"] > 0
    assert inventory["in_zone_m3"] > 0
    assert material["ledger"]["received_m3"] == received
    assert inventory["total_m3"] == pytest.approx(received, abs=1e-8)
    spill_shape = sum(h * grid["cell_size"] ** 2 for h, code in zip(grid["coal_thickness_m"], grid["zone_codes"]) if code == 1)
    assert inventory["spilled_m3"] == pytest.approx(spill_shape, abs=1e-8)
    assert all(h == 0 for h, code in zip(grid["coal_thickness_m"], grid["zone_codes"]) if code == 0)
