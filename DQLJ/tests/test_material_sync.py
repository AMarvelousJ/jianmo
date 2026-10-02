import pytest
from fastapi.testclient import TestClient

from yard_motion.api import create_app
from test_stacking import stacking_world
from yard_motion.world import World


def test_delta_reconstructs_same_version_shape_and_ledger_without_full_arrays():
    world, _ = stacking_world()
    with TestClient(create_app(world, run_clock=False)) as client:
        full = client.get("/api/material/grid").json()
        world.advance(.1)
        response = client.get("/api/material/update", params=dict(
            server_instance_id=full["server_instance_id"], base_version=full["material"]["version"]))
        assert response.status_code == 200
        delta = response.json()
        assert delta["base_version"] == full["material"]["version"]
        assert delta["new_version"] == delta["material"]["version"]
        assert "grid" not in delta
        assert delta["jobs"] and delta["zone_occupancy"] and "persistence" in delta
        heights = full["grid"]["coal_thickness_m"]
        for index, height in zip(delta["changes"]["indices"], delta["changes"]["coal_thickness_m"]):
            heights[index] = height
        current = client.get("/api/material/grid").json()
        assert heights == current["grid"]["coal_thickness_m"]
        assert delta["material"] == current["material"]
        assert sum(heights) * full["grid"]["cell_size"] ** 2 == pytest.approx(delta["material"]["inventory"]["total_m3"], abs=1e-8)


def test_skipped_versions_are_coalesced_reset_and_old_instance_require_full():
    world, op = stacking_world()
    full = world.material_grid()
    for _ in range(10):
        world.advance(.1)
    delta = world.material_update(world.instance, full["material"]["version"])
    assert delta["new_version"] > delta["base_version"] + 1
    heights = full["grid"]["coal_thickness_m"]
    for index, height in zip(delta["changes"]["indices"], delta["changes"]["coal_thickness_m"]):
        heights[index] = height
    assert heights == world.material_grid()["grid"]["coal_thickness_m"]
    op.send("terminate_job")
    world.init_material("empty", confirm=True)
    with TestClient(create_app(world, run_clock=False)) as client:
        for instance, version in ((world.instance, delta["new_version"]), ("old-instance", world.material_grid()["material"]["version"])):
            rejected = client.get("/api/material/update", params=dict(server_instance_id=instance, base_version=version))
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "MATERIAL_FULL_REQUIRED"


def test_restarted_material_rejects_old_baseline_and_keeps_versioned_context(tmp_path):
    path = tmp_path / "material.json"
    world = World(snapshot_path=path)
    world.init_material("preset")
    full = world.material_grid()
    restarted = World(snapshot_path=path)
    with TestClient(create_app(restarted, run_clock=False)) as client:
        response = client.get("/api/material/update", params=dict(server_instance_id=full["server_instance_id"], base_version=full["material"]["version"]))
        assert response.status_code == 409
        current = client.get("/api/material/grid").json()
        assert current["server_instance_id"] != full["server_instance_id"]
        empty = client.get("/api/material/update", params=dict(server_instance_id=current["server_instance_id"], base_version=current["material"]["version"])).json()
        assert empty["changes"]["indices"] == []
        assert empty["material"] == current["material"]
        assert empty["persistence"]["enabled"] is True
