from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_loading_task_manager,
    get_scene_state,
    get_world,
)
from app.core.loading.rate_model import LoadingRateModel
from app.main import app
from app.models.loading import LoadingTaskCreateRequest

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_loading_runtime():
    world = get_world()
    scene_state = get_scene_state()
    original_scene = scene_state.get_scene().model_copy(deep=True)
    world.reset()
    yield
    world.reset()
    scene_state.update_scene(original_scene)


def create_demo_task():
    manager = get_loading_task_manager()
    task, created = manager.create_task(
        LoadingTaskCreateRequest(
            request_id=str(uuid4()),
            plan_id=manager.plan.plan_id,
            mode="demo",
        )
    )
    assert created is True
    return task


def test_default_plan_totals_mapping_and_all_paths_are_valid():
    manager = get_loading_task_manager()
    plan = manager.get_plan()
    validation = manager.validate_plan()

    assert plan.total_target_kg == 52_100_000
    assert [batch.batch_no for batch in plan.batches()] == list(range(1, 13))
    assert [batch.hold_no for batch in plan.rounds[2].batches] == [
        "No.1",
        "No.5",
    ]
    assert plan.hold_mapping == {
        "No.1": "R1",
        "No.2": "R2",
        "No.3": "R3",
        "No.4": "R4",
        "No.5": "R5",
    }
    assert validation.valid is True
    assert validation.calculated_total_kg == 52_100_000
    assert validation.round_totals_kg == {
        1: 27_000_000,
        2: 23_700_000,
        3: 1_400_000,
    }
    assert validation.hold_totals_kg == {
        "No.1": 10_300_000,
        "No.2": 11_100_000,
        "No.3": 8_300_000,
        "No.4": 11_200_000,
        "No.5": 11_200_000,
    }
    assert len(validation.path_checks) == 12
    assert all(item.feasible for item in validation.path_checks)


def test_rate_model_carries_fractional_kg_and_clips_final_step():
    model = LoadingRateModel()
    total = 0
    for _ in range(3):
        total += model.increment_kg(
            task_id="task",
            batch_no=1,
            rate_tph=1.0,
            loading_scale=1.0,
            base_dt=1.0,
            remaining_kg=10 - total,
        )
    assert total == 0

    increment = model.increment_kg(
        task_id="task",
        batch_no=1,
        rate_tph=1.0,
        loading_scale=1.0,
        base_dt=1.0,
        remaining_kg=1,
    )
    assert increment == 1

    clipped = model.increment_kg(
        task_id="task",
        batch_no=2,
        rate_tph=8000.0,
        loading_scale=600.0,
        base_dt=10.0,
        remaining_kg=123,
    )
    assert clipped == 123


def test_demo_workflow_completes_exactly_with_expected_aggregates():
    world = get_world()
    manager = get_loading_task_manager()
    create_demo_task()

    for _ in range(4000):
        world.step(0.1)
        task = manager.get_current()
        assert task is not None
        if task.status in manager.TERMINAL_STATUSES:
            break

    assert task.status == "completed"
    assert task.loaded_total_kg == 52_100_000
    assert 260.0 <= task.demo_elapsed_s <= 285.0
    assert task.logical_business_s == pytest.approx(73_845.0)
    assert [item.loaded_kg for item in task.round_progress] == [
        27_000_000,
        23_700_000,
        1_400_000,
    ]
    assert {item.hold_id: item.loaded_kg for item in task.hold_progress} == {
        "R1": 10_300_000,
        "R2": 11_100_000,
        "R3": 8_300_000,
        "R4": 11_200_000,
        "R5": 11_200_000,
    }
    assert all(item.status == "completed" for item in task.batch_progress)
    event_types = {
        event.event_type for event in manager.list_events(task.task_id)
    }
    assert {
        "loading_task_created",
        "loading_drainage_started",
        "loading_drainage_completed",
        "tonnage_updated",
        "loading_task_completed",
    } <= event_types


def test_normal_mode_uses_unscaled_motion_and_loading_time():
    manager = get_loading_task_manager()
    task, _ = manager.create_task(
        LoadingTaskCreateRequest(
            request_id=str(uuid4()),
            plan_id=manager.plan.plan_id,
            mode="normal",
        )
    )
    assert task.motion_scale == 1.0
    assert task.loading_scale == 1.0


def test_pause_freezes_position_time_tonnage_and_resume_continues():
    world = get_world()
    manager = get_loading_task_manager()
    task = create_demo_task()

    for _ in range(1200):
        world.step(0.1)
        task = manager.get_current()
        if task.status == "loading" and task.loaded_total_kg > 0:
            break

    paused = manager.pause_task(task.task_id)
    before = (
        world.sim_time,
        paused.demo_elapsed_s,
        paused.logical_business_s,
        paused.loaded_total_kg,
        {
            axis_id: axis.current
            for axis_id, axis in world.loader.axes.items()
        },
    )
    world.step(10.0)
    frozen = manager.get_current()
    after = (
        world.sim_time,
        frozen.demo_elapsed_s,
        frozen.logical_business_s,
        frozen.loaded_total_kg,
        {
            axis_id: axis.current
            for axis_id, axis in world.loader.axes.items()
        },
    )
    assert frozen.status == "paused"
    assert after == before

    resumed = manager.resume_task(task.task_id)
    assert resumed.status == "loading"
    world.step(0.1)
    assert manager.get_current().loaded_total_kg > frozen.loaded_total_kg


def test_hatch_close_pauses_and_reopen_revalidates_before_resume():
    world = get_world()
    manager = get_loading_task_manager()
    scene_state = get_scene_state()
    task = create_demo_task()

    scene = scene_state.get_scene().model_copy(deep=True)
    vessel = next(item for item in scene.vessels if item.id == "Vessel-R")
    hold = next(item for item in vessel.holds if item.id == "R4")
    hold.cover_state = "closed"
    scene_state.update_scene(scene)
    world.step(0.1)

    paused = manager.get_current()
    assert paused.status == "paused"
    assert paused.failure_code == "HATCH_COVER_CLOSED"
    assert paused.loaded_total_kg == 0

    reopened_scene = scene_state.get_scene().model_copy(deep=True)
    vessel = next(
        item for item in reopened_scene.vessels if item.id == "Vessel-R"
    )
    hold = next(item for item in vessel.holds if item.id == "R4")
    hold.cover_state = "open"
    current_revision = scene_state.update_scene(reopened_scene).revision

    resumed = manager.resume_task(task.task_id)
    assert resumed.status == "positioning"
    assert resumed.scene_revision == current_revision
    assert resumed.current_path_task_id is None


def test_unexpected_belt_stop_pauses_active_loading_batch():
    world = get_world()
    manager = get_loading_task_manager()
    create_demo_task()

    for _ in range(1200):
        world.step(0.1)
        task = manager.get_current()
        if task.status == "loading" and task.loaded_total_kg > 0:
            break

    world.loader.belt.stop()
    world.step(0.1)
    paused = manager.get_current()
    assert paused.status == "paused"
    assert paused.failure_code == "BELT_INTERLOCK_VIOLATION"
    assert world.loader.belt.running is False


def test_belt_running_during_positioning_is_stopped_and_pauses_task():
    world = get_world()
    manager = get_loading_task_manager()
    create_demo_task()

    world.loader.set_belt(4.8, True)
    world.step(0.1)

    paused = manager.get_current()
    assert paused.status == "paused"
    assert paused.failure_code == "BELT_INTERLOCK_VIOLATION"
    assert world.loader.belt.running is False


def test_drainage_pause_freezes_countdown_and_motion_fault_fails():
    world = get_world()
    manager = get_loading_task_manager()
    task = create_demo_task()

    for _ in range(1800):
        world.step(0.1)
        task = manager.get_current()
        if task.status == "waiting_drainage":
            break
    assert task.status == "waiting_drainage"

    paused = manager.pause_task(task.task_id)
    remaining = paused.drainage_remaining_demo_s
    logical = paused.logical_business_s
    world.step(5.0)
    frozen = manager.get_current()
    assert frozen.drainage_remaining_demo_s == remaining
    assert frozen.logical_business_s == logical

    manager.resume_task(task.task_id)
    world.step(0.1)
    progressed = manager.get_current()
    assert progressed.drainage_remaining_demo_s < remaining

    world.loader.set_axis_target("travel", world.loader.axes["travel"].current + 1)
    world.loader.start_axis("travel")
    world.step(0.1)
    failed = manager.get_current()
    assert failed.status == "failed"
    assert failed.failure_code == "DRAINAGE_INTERLOCK_VIOLATION"


def test_loading_api_idempotency_control_locks_and_reset_contract():
    manager = get_loading_task_manager()
    body = {
        "request_id": str(uuid4()),
        "plan_id": manager.plan.plan_id,
        "mode": "demo",
    }
    created = client.post("/api/loading-tasks", json=body)
    assert created.status_code == 201
    task_id = created.json()["task_id"]

    repeated = client.post("/api/loading-tasks", json=body)
    assert repeated.status_code == 200
    assert repeated.json()["task_id"] == task_id

    idempotency_conflict = client.post(
        "/api/loading-tasks",
        json={**body, "plan_id": "another-plan"},
    )
    assert idempotency_conflict.status_code == 409
    assert (
        idempotency_conflict.json()["detail"]["code"]
        == "IDEMPOTENCY_CONFLICT"
    )

    second = client.post(
        "/api/loading-tasks",
        json={**body, "request_id": str(uuid4())},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "LOADING_TASK_CONFLICT"

    manual = client.post(
        "/api/axis/travel/target",
        json={"target": 1.0, "velocity": 0.5},
    )
    assert manual.status_code == 409
    assert manual.json()["detail"]["code"] == "AUTOMATION_LOCKED"

    path = client.post(
        "/api/path-plans/preview",
        json={
            "vessel_id": "Vessel-R",
            "hold_id": "R1",
            "column": 5,
            "row": 4,
        },
    )
    assert path.status_code == 409
    assert path.json()["detail"]["code"] == "LOADING_TASK_ACTIVE"

    assert client.post(f"/api/loading-tasks/{task_id}/pause").status_code == 200
    global_resume = client.post("/api/simulation/resume")
    assert global_resume.status_code == 409
    assert (
        global_resume.json()["detail"]["code"]
        == "INVALID_LOADING_TASK_STATE"
    )
    assert client.post(f"/api/loading-tasks/{task_id}/resume").status_code == 200
    cancelled = client.post(f"/api/loading-tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    reset = client.post(f"/api/loading-tasks/{task_id}/reset")
    assert reset.status_code == 200
    assert reset.json()["snapshot"]["loading_task"] is None
    assert client.get("/api/loading-tasks/current").json() is None
    assert any(
        item["task_id"] == task_id
        for item in client.get("/api/loading-tasks").json()
    )
