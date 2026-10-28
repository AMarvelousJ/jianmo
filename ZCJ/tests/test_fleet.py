import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.fleet import FleetConfiguration, FleetMachine, JogRequest, make_app
from app.config.loader import load_loader_profile
from app.config.scene import load_scene_config
from app.models.loading import LoadingTaskCreateRequest


def configured(number=1):
    machine = FleetMachine(number)
    scene = load_scene_config()
    if number > 3:
        scene.vessels = [scene.vessels[1 if number < 6 else 0]]
    machine.configure(FleetConfiguration(**scene.model_dump(),
        geometry=load_loader_profile().geometry, travel_min=-45, travel_max=50))
    machine.select_side(scene.vessels[-1].id)
    return machine


def start(machine):
    return machine.manager.create_task(LoadingTaskCreateRequest(
        request_id=f"test-{machine.number}", plan_id=machine.manager.plan.plan_id, mode="demo"))[0]


def jog(machine, session, sequence, **values):
    axes = dict.fromkeys(machine.world.loader.axes, 0.0)
    axes.update(values)
    return machine.jog(JogRequest(session=session, sequence=sequence, axes=axes))


def test_seven_parallel_tasks_and_manual_replan_preserves_cargo():
    fleet = [configured(i) for i in range(1, 8)]
    for machine in fleet:
        start(machine)
    for _ in range(20000):
        for machine in fleet:
            machine.step(.1)
        task = fleet[0].manager.get_current()
        if task.status == "loading" and task.loaded_total_kg > 0:
            break
    else:
        pytest.fail("First machine never loaded cargo")
    first = fleet[0]
    before = first.manager.get_current()
    loaded = [b.loaded_kg for b in before.batch_progress]
    session = first.enter_manual()["session"]
    for seq in range(30):
        jog(first, session, seq, travel=.8, slew=.4, boom_luff=.2, boom_extension=.3, chute_rotate=.5)
        for machine in fleet:
            machine.step(.1)
    paused = first.manager.get_current()
    assert paused.status == "paused"
    assert [b.loaded_kg for b in paused.batch_progress] == loaded
    assert first.world.loader.axes["travel"].current != before.current_target_world_point.x
    assert any(m.manager.get_current().loaded_total_kg > 0 for m in fleet[1:])
    first.exit_manual()
    resumed = first.manager.resume_task(before.task_id)
    assert resumed.status == "positioning"
    assert resumed.current_path_task_id is None
    assert resumed.loaded_total_kg == before.loaded_total_kg
    first.step(.1)
    assert first.manager.get_current().current_path_task_id != before.current_path_task_id
    for _ in range(30000):
        for machine in fleet:
            machine.step(.1)
        tasks = [m.manager.get_current() for m in fleet]
        if all(t.status == "completed" for t in tasks):
            break
        assert all(t.status not in {"failed", "cancelled", "paused"} for t in tasks)
    else:
        pytest.fail(str([(t.status, t.current_phase) for t in tasks]))
    assert all(t.loaded_total_kg == 52_100_000 for t in tasks)
    assert len({t.task_id for t in tasks}) == 7


def test_jog_lease_limits_sequence_and_old_session():
    machine = configured()
    session = machine.enter_manual()["session"]
    jog(machine, session, 2, travel=1)
    machine.step(.1)
    position = machine.world.loader.axes["travel"].current
    jog(machine, session, 1, travel=-1)
    assert machine.world.loader.axes["travel"].target == 50
    machine.deadline = time.monotonic() - 1
    machine.step(.1)
    assert machine.world.loader.axes["travel"].current == position
    assert not any(a.running for a in machine.world.loader.axes.values())
    machine.exit_manual()
    with pytest.raises(HTTPException):
        jog(machine, session, 3, travel=1)
    new = machine.enter_manual()["session"]
    assert new != session
    with pytest.raises(HTTPException):
        jog(machine, new, 4, travel=float("nan"))
    machine.world.loader.axes["travel"].reset(49.99)
    jog(machine, new, 5, travel=1)
    machine.step(.1)
    assert machine.world.loader.axes["travel"].current == 50


def test_fleet_http_state_isolation_and_required_side():
    a, b = configured(1), configured(2)
    a.selected_vessel = None
    parent = FastAPI()
    parent.mount("/api/fleet/01", make_app(a, parent))
    parent.mount("/api/fleet/02", make_app(b, parent))
    with TestClient(parent) as client:
        response = client.post("/api/fleet/01/api/loading-tasks", json={
            "request_id": "missing-side", "plan_id": a.manager.plan.plan_id, "mode": "demo"})
        assert response.status_code == 409
        assert client.get("/api/fleet/02/api/state").json()["loader_id"] == "SL15-02"
        assert client.post("/api/fleet/01/api/selection", json={"vessel_id": "missing"}).status_code == 422
        assert client.post("/api/fleet/01/api/selection", json={"vessel_id": "Vessel-L"}).status_code == 200
        task = start(a)
        assert client.post("/api/fleet/01/api/selection", json={"vessel_id": "Vessel-R"}).status_code == 409
        response = client.post("/api/fleet/01/api/manual/enter")
        assert response.status_code == 200
        assert a.manager.get_current().status == "paused"
        assert b.manager.get_current() is None
        assert client.post(f"/api/fleet/01/api/loading-tasks/{task.task_id}/resume").status_code == 200
        assert a.session is None


def test_clock_routes_advance_the_assigned_world_once():
    a, b = configured(1), configured(2)
    parent = FastAPI()
    parent.mount("/api/fleet/01", make_app(a, parent))
    parent.mount("/api/fleet/02", make_app(b, parent))
    try:
        with TestClient(parent) as client:
            assert client.put("/api/fleet/01/api/simulation/clock/clients/test-a").status_code == 200
            assert client.put("/api/fleet/01/api/simulation/clock/clients/test-b").status_code == 200
            time.sleep(.2)
            assert a.world.sim_time >= .1
            assert b.world.sim_time == 0
            assert a.clock.status().active_clients == 2
            assert b.clock.status().active_clients == 0
    finally:
        a.clock.stop()
        b.clock.stop()
