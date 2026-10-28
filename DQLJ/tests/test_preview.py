import pytest
from fastapi.testclient import TestClient
from yard_motion.preview import create_preview_app, preview_config
from yard_motion.world import World
from yard_motion.errors import MotionError


def test_preview_limits_are_enforced_for_all_machines_without_changing_default():
    normal = World()
    config = preview_config()
    world = World(config=config)
    for machine in config["machines"]:
        limits = [-20, 200] if machine["role"] == "Stacking" else [-80, 260]
        id = machine["machine_id"]
        lease = world.acquire(id, "preview-test")
        for seq, target in enumerate(limits, 1):
            world.command(id, "preview-test", lease["token"], lease["generation"], str(seq), seq,
                          "set_targets", {"targets": {"slew": target}})
        for seq, target in enumerate([limits[0] - .1, limits[1] + .1], 3):
            with pytest.raises(MotionError):
                world.command(id, "preview-test", lease["token"], lease["generation"], str(seq), seq,
                              "set_targets", {"targets": {"slew": target}})
        assert normal.machines[id].axes["slew"].config["minimum"] == -90
        assert normal.machines[id].axes["slew"].config["maximum"] == 90


def test_preview_accepts_motion_and_blocks_material_work():
    with TestClient(create_preview_app()) as client:
        assert client.get("/api/machines").json()["config_version"] == "yard-video-preview-v3"
        lease = client.post("/api/machines/ST01/control/acquire", json={"client_id": "test"}).json()
        base = dict(client_id="test", token=lease["token"], generation=lease["generation"])
        assert client.post("/api/machines/ST01/commands", json=dict(base, command_id="belt", command_seq=1,
                           kind="set_belt", payload={"speed": 2})).status_code == 200
        assert client.post("/api/machines/ST01/commands", json=dict(base, command_id="job", command_seq=2,
                           kind="start_job", payload={})).status_code == 409
        assert client.post("/api/material/scene", json={}).status_code == 409

