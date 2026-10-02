from fastapi.testclient import TestClient
import pytest

from yard_motion.api import create_app
from yard_motion.errors import MotionError
from test_stacking import Operator, START_PAYLOAD, ready_world


def scene_controls(world, client_id="scene-test"):
    st, rc = (world.acquire(machine_id, client_id) for machine_id in ("ST01", "RC01"))
    return dict(machine_id="ST01", client_id=client_id, token=st["token"], generation=st["generation"],
                controls=[dict(machine_id="RC01", token=rc["token"], generation=rc["generation"])])


def test_unauthenticated_scene_write_is_rejected_without_mutation():
    world = ready_world()
    before = world.material_grid()
    with TestClient(create_app(world, run_clock=False)) as client:
        response = client.post("/api/material/scene", json={"mode": "preset", "confirm": True})
    assert response.status_code in (403, 422)
    assert world.material_grid() == before


def test_scene_reset_requires_both_controls_confirmation_and_is_idempotent():
    world = ready_world()
    credentials = scene_controls(world)
    body = dict(credentials, command_id="scene-reset", command_seq=1, mode="preset", confirm=True)
    with TestClient(create_app(world, run_clock=False)) as client:
        missing = client.post("/api/material/scene", json=dict(body, controls=[]))
        assert missing.status_code == 403
        unconfirmed = client.post("/api/material/scene", json=dict(body, confirm=False))
        assert unconfirmed.status_code == 409
        assert unconfirmed.json()["detail"]["code"] == "CONFIRM_REQUIRED"
        accepted = client.post("/api/material/scene", json=body)
        assert accepted.status_code == 200
        before = world.material_grid()
        replay = client.post("/api/material/scene", json=body)
        assert replay.json() == accepted.json()
        assert world.material_grid() == before
        stale = client.post("/api/material/scene", json=dict(body, command_id="new-id"))
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "STALE_COMMAND"


@pytest.mark.parametrize("blocked", ["axis", "belt", "wheel", "job", "paused_job"])
def test_reset_rejects_moving_devices_and_active_or_paused_jobs(blocked):
    world = ready_world()
    st, rc = Operator(world, "ST01", "scene-test"), Operator(world, "RC01", "scene-test")
    if blocked == "axis":
        rc.send("set_targets", {"targets": {"travel": -350}})
    elif blocked in ("belt", "wheel"):
        rc.send("set_" + blocked, {"speed": 1})
    else:
        st.send("start_job", START_PAYLOAD)
        if blocked == "paused_job":
            st.send("pause_job")
    controls = [dict(machine_id="RC01", token=rc.creds[1], generation=rc.creds[2])]
    before = world.material_grid()
    with pytest.raises(MotionError) as rejected:
        st.send("reset_material", dict(mode="preset", confirm=True, controls=controls))
    assert rejected.value.code == ("JOB_ACTIVE" if "job" in blocked else "MACHINE_MOVING")
    assert world.material_grid() == before


def test_other_client_or_cross_machine_credentials_cannot_clear_material():
    world = ready_world()
    st, rc = Operator(world, "ST01", "client-a"), Operator(world, "RC01", "client-b")
    controls = [dict(machine_id="RC01", token=rc.creds[1], generation=rc.creds[2])]
    before = world.material_grid()
    with pytest.raises(MotionError) as refused:
        st.send("reset_material", dict(mode="preset", confirm=True, controls=controls))
    assert refused.value.code == "CONTROL_REQUIRED"
    with pytest.raises(MotionError) as crossed:
        world.command("RC01", *st.creds, "crossed", 1, "start_job", START_PAYLOAD)
    assert crossed.value.code == "CONTROL_REQUIRED"
    assert world.material_grid() == before
