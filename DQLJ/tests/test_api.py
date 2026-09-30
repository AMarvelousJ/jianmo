from fastapi.testclient import TestClient
from yard_motion.api import create_app
from yard_motion.world import World


def test_api_owns_machine_moves_and_rejects_competing_client():
    world = World()
    client = TestClient(create_app(world, run_clock=False))
    assert len(client.get("/api/machines").json()["machines"]) == 21
    lease = client.post("/api/machines/ST01/control/acquire", json={"client_id": "a"}).json()
    assert client.post("/api/machines/ST01/control/acquire", json={"client_id": "b"}).status_code == 409
    command = dict(client_id="a", token=lease["token"], generation=lease["generation"],
                   command_id="move", command_seq=1, kind="set_targets", payload={"targets": {"travel": -505}})
    assert client.post("/api/machines/ST01/commands", json=command).status_code == 200
    world.advance(1)
    state = client.get("/api/state").json()
    assert state["machines"]["ST01"]["axes"]["travel"]["position"] > -510
    assert state["machines"]["ST02"]["axes"]["travel"]["position"] == -510


def test_malformed_axis_returns_structured_error_not_server_error():
    world = World()
    client = TestClient(create_app(world, run_clock=False))
    lease = world.acquire("ST01", "a")
    for index, axis in enumerate([[], {}, 12]):
        request = dict(client_id="a", token=lease["token"], generation=lease["generation"],
                       command_id=str(index), command_seq=index+1, kind="jog",
                       payload=dict(axis=axis, direction=1, speed=1))
        response = client.post("/api/machines/ST01/commands", json=request)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "INVALID_COMMAND"
