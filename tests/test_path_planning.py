from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_world
from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.grid_transformer import GridTransformer
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.plan_store import PathPlanStore
from app.core.path_planning.target_solver import TargetSolver
from app.core.path_planning.task_manager import PathTaskManager
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.config.loader import create_default_ship_loader
from app.config.scene import load_scene_config
from app.main import app
from app.models.path_planning import GridTargetRequest, PathPlan


@pytest.fixture()
def client():
    test_client = TestClient(app)
    original_scene = test_client.get("/api/scene").json()
    test_client.post("/api/simulation/reset")
    yield test_client
    test_client.post("/api/simulation/reset")
    test_client.put("/api/scene", json=original_scene)


def preview(
    client: TestClient,
    *,
    vessel_id: str = "Vessel-R",
    hold_id: str = "R2",
    column: int = 9,
    row: int = 4,
):
    return client.post(
        "/api/path-plans/preview",
        json={
            "vessel_id": vessel_id,
            "hold_id": hold_id,
            "column": column,
            "row": row,
        },
    )


def create_task(client: TestClient, plan_id: str, request_id: str | None = None):
    return client.post(
        "/api/path-tasks",
        json={
            "request_id": request_id or f"test-{uuid4().hex}",
            "plan_id": plan_id,
        },
    )


def test_default_scene_has_explicit_grid_path_configuration(client: TestClient):
    scene = client.get("/api/scene").json()
    assert scene["revision"] >= 1
    for vessel in scene["vessels"]:
        assert vessel["yaw_deg"] == pytest.approx(0.0)
        for hold in vessel["holds"]:
            assert hold["grid"] == {
                "columns": 10,
                "rows": 8,
                "index_base": 1,
                "column_direction": "bow_to_stern",
                "row_direction": "port_to_starboard",
            }
            assert hold["hatch_plane_offset_z_m"] == pytest.approx(2.02)
            assert hold["cover_state"] == "open"


def test_grid_endpoint_returns_80_bow_up_cells(client: TestClient):
    response = client.get("/api/vessels/Vessel-R/holds/R2/grid")
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == 10
    assert body["rows"] == 8
    assert body["column_direction"] == "bow_to_stern"
    assert body["row_direction"] == "port_to_starboard"
    assert len(body["cells"]) == 80
    cell = next(
        item
        for item in body["cells"]
        if item["column"] == 9 and item["row"] == 4
    )
    assert cell["local_center_m"] == pytest.approx([2.87, -0.375, 0.0])
    assert cell["world_center_m"] == pytest.approx([3.87, 23.625, 3.62])


def test_standard_preview_matches_canonical_inverse_solution(client: TestClient):
    response = preview(client)
    assert response.status_code == 200
    body = response.json()
    assert body["feasible"] is True
    assert body["target"]["world_point"] == pytest.approx([3.87, 23.625, 4.62])
    assert body["axis_solution"] == pytest.approx(
        {
            "travel": 3.87,
            "slew": 0.0,
            "boom_luff": 9.656884201893584,
            "boom_extension": 7.464578548349227,
            "chute_rotate": -90.0,
        }
    )
    assert [stage["stage"] for stage in body["stages"]] == [
        "safe_luff",
        "safe_retract",
        "safe_slew",
        "travel",
        "target_luff",
        "final_approach",
    ]
    assert body["estimated_duration_s"] == pytest.approx(96.55734338254547)
    assert body["verification_error"]["horizontal_m"] <= 0.10
    assert body["verification_error"]["vertical_m"] <= 0.10
    assert body["verification_error"]["heading_deg"] <= 1.0


def test_left_side_preview_uses_180_degree_safe_slew(client: TestClient):
    response = preview(
        client,
        vessel_id="Vessel-L",
        hold_id="L2",
        column=5,
        row=4,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["axis_solution"]["slew"] == pytest.approx(180.0)
    assert body["stages"][2]["stage"] == "safe_slew"
    assert body["stages"][2]["axis_targets"]["slew"] == pytest.approx(180.0)
    assert body["axis_solution"]["chute_rotate"] == pytest.approx(90.0)

    created = create_task(client, body["plan_id"])
    assert created.status_code == 201
    terminal = None
    for _ in range(180):
        snapshot = client.post("/api/simulation/step", json={"dt": 2.0}).json()
        if snapshot["path_task"]["status"] in {"arrived", "failed"}:
            terminal = snapshot["path_task"]
            break
    assert terminal is not None
    assert terminal["status"] == "arrived"
    task = client.get(f"/api/path-tasks/{created.json()['task_id']}").json()
    assert task["stages"][2]["status"] == "completed"


def test_nonzero_vessel_yaw_rotates_grid_and_default_heading(client: TestClient):
    scene = client.get("/api/scene").json()
    scene["vessels"][1]["yaw_deg"] = 90.0
    assert client.put("/api/scene", json=scene).status_code == 200

    grid = client.get("/api/vessels/Vessel-R/holds/R2/grid")
    assert grid.status_code == 200
    cell = next(
        item
        for item in grid.json()["cells"]
        if item["column"] == 10 and item["row"] == 4
    )
    assert cell["world_center_m"] == pytest.approx([12.375, 16.69, 3.62])

    plan = preview(client, column=10, row=4)
    assert plan.status_code == 200
    assert plan.json()["target"]["world_point"] == pytest.approx([12.375, 16.69, 4.62])
    assert plan.json()["target"]["heading_deg"] == pytest.approx(90.0)
    assert plan.json()["axis_solution"]["chute_rotate"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("column", "row", "field"),
    [(0, 4, "column"), (11, 4, "column"), (9, 0, "row"), (9, 9, "row")],
)
def test_grid_bounds_return_structured_error(
    client: TestClient,
    column: int,
    row: int,
    field: str,
):
    response = preview(client, column=column, row=row)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "GRID_OUT_OF_RANGE"
    assert detail["context"]["field"] == field


def test_request_validation_uses_structured_error_contract(client: TestClient):
    response = client.post(
        "/api/path-plans/preview",
        json={"hold_id": "R2", "column": 9, "row": 4},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["context"]["path"] == "/api/path-plans/preview"
    assert detail["context"]["errors"][0]["field"] == "vessel_id"


def test_preview_rejects_missing_height_and_closed_cover(client: TestClient):
    scene = client.get("/api/scene").json()
    hold = scene["vessels"][1]["holds"][1]
    hold["hatch_plane_offset_z_m"] = None
    assert client.put("/api/scene", json=scene).status_code == 200
    missing = preview(client)
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "HATCH_HEIGHT_MISSING"

    scene = client.get("/api/scene").json()
    hold = scene["vessels"][1]["holds"][1]
    hold["hatch_plane_offset_z_m"] = 2.02
    hold["cover_state"] = "closed"
    assert client.put("/api/scene", json=scene).status_code == 200
    closed = preview(client)
    assert closed.status_code == 400
    assert closed.json()["detail"]["code"] == "HATCH_COVER_CLOSED"

    scene = client.get("/api/scene").json()
    hold = scene["vessels"][1]["holds"][1]
    hold["cover_state"] = None
    assert client.put("/api/scene", json=scene).status_code == 200
    missing_cover = preview(client)
    assert missing_cover.status_code == 400
    assert missing_cover.json()["detail"]["code"] == "HATCH_COVER_STATE_MISSING"


def test_scene_revision_invalidates_preview(client: TestClient):
    plan = preview(client).json()
    scene = client.get("/api/scene").json()
    update = client.put("/api/scene", json=scene)
    assert update.status_code == 200
    assert update.json()["revision"] > plan["scene_revision"]

    response = create_task(client, plan["plan_id"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SCENE_REVISION_MISMATCH"


def test_scene_change_during_task_pauses_and_requires_replanning(client: TestClient):
    plan = preview(client).json()
    created = create_task(client, plan["plan_id"])
    task_id = created.json()["task_id"]
    client.post("/api/simulation/step", json={"dt": 1.0})

    scene = client.get("/api/scene").json()
    assert client.put("/api/scene", json=scene).status_code == 200
    snapshot = client.post("/api/simulation/step", json={"dt": 1.0}).json()
    assert snapshot["path_task"]["status"] == "paused"
    assert snapshot["path_task"]["pause_reason"] == "scene_changed"

    resume = client.post(f"/api/path-tasks/{task_id}/resume")
    assert resume.status_code == 409
    assert resume.json()["detail"]["code"] == "SCENE_REVISION_MISMATCH"
    client.post(f"/api/path-tasks/{task_id}/cancel")


def test_six_stage_task_arrives_and_is_recorded(client: TestClient):
    plan = preview(client).json()
    response = create_task(client, plan["plan_id"])
    assert response.status_code == 201
    task_id = response.json()["task_id"]
    first_snapshot = client.get("/api/state").json()
    assert first_snapshot["path_task"]["actual_point"] is not None
    assert first_snapshot["path_task"]["error"]["horizontal_m"] > 0

    terminal = None
    for _ in range(120):
        snapshot = client.post("/api/simulation/step", json={"dt": 1.0}).json()
        summary = snapshot["path_task"]
        if summary["status"] in {"arrived", "failed"}:
            terminal = summary
            break
    assert terminal is not None
    assert terminal["status"] == "arrived"
    assert terminal["error"]["horizontal_m"] <= 0.10
    assert terminal["error"]["vertical_m"] <= 0.10
    assert terminal["error"]["heading_deg"] <= 1.0
    assert client.get("/api/path-tasks/current").json() is None

    task = client.get(f"/api/path-tasks/{task_id}").json()
    assert [stage["stage"] for stage in task["stages"]] == [
        "safe_luff",
        "safe_retract",
        "safe_slew",
        "travel",
        "target_luff",
        "final_approach",
    ]
    assert all(stage["status"] in {"completed", "skipped"} for stage in task["stages"])

    next_plan = preview(client, hold_id="R4", column=3, row=6)
    assert next_plan.status_code == 200
    next_task = create_task(client, next_plan.json()["plan_id"])
    assert next_task.status_code == 201
    assert next_task.json()["target"]["hold_id"] == "R4"
    client.post(f"/api/path-tasks/{next_task.json()['task_id']}/cancel")


def test_task_pause_lock_resume_cancel_and_idempotency(client: TestClient):
    plan = preview(client).json()
    request_id = f"idempotent-{uuid4().hex}"
    first = create_task(client, plan["plan_id"], request_id)
    assert first.status_code == 201
    task_id = first.json()["task_id"]
    replay = create_task(client, plan["plan_id"], request_id)
    assert replay.status_code == 200
    assert replay.json()["task_id"] == task_id

    client.post("/api/simulation/step", json={"dt": 1.0})
    paused = client.post(f"/api/path-tasks/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    manual = client.post(
        "/api/axis/travel/target",
        json={"target": 0.0, "velocity": 0.5},
    )
    assert manual.status_code == 409
    assert manual.json()["detail"]["code"] == "AUTOMATION_LOCKED"
    belt = client.post("/api/belt", json={"speed": 4.8, "running": True})
    assert belt.status_code == 409
    assert belt.json()["detail"]["code"] == "PATH_TASK_ACTIVE"
    direct_resume = client.post("/api/simulation/resume")
    assert direct_resume.status_code == 409
    assert direct_resume.json()["detail"]["code"] == "INVALID_TASK_STATE"

    resumed = client.post(f"/api/path-tasks/{task_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    cancelled = client.post(f"/api/path-tasks/{task_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    repeated_cancel = client.post(f"/api/path-tasks/{task_id}/cancel")
    assert repeated_cancel.status_code == 200
    assert repeated_cancel.json()["status"] == "cancelled"


def test_same_request_id_with_different_plan_conflicts(client: TestClient):
    first_plan = preview(client, column=9, row=4).json()
    second_plan = preview(client, column=8, row=4).json()
    request_id = f"conflict-{uuid4().hex}"
    created = create_task(client, first_plan["plan_id"], request_id)
    assert created.status_code == 201
    conflict = create_task(client, second_plan["plan_id"], request_id)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    client.post(f"/api/path-tasks/{created.json()['task_id']}/cancel")


def test_second_active_task_is_rejected(client: TestClient):
    first_plan = preview(client, column=9, row=4).json()
    second_plan = preview(client, column=8, row=4).json()
    first = create_task(client, first_plan["plan_id"])
    assert first.status_code == 201
    second = create_task(client, second_plan["plan_id"])
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "TASK_CONFLICT"
    client.post(f"/api/path-tasks/{first.json()['task_id']}/cancel")


def test_preview_rejects_running_belt_and_disabled_axis(client: TestClient):
    belt = client.post("/api/belt", json={"speed": 4.8, "running": True})
    assert belt.status_code == 200
    blocked = preview(client)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "BELT_RUNNING"
    client.post("/api/belt", json={"speed": 0.0, "running": False})

    world = get_world()
    world.loader.axes["slew"].enabled = False
    try:
        disabled = preview(client)
        assert disabled.status_code == 400
        assert disabled.json()["detail"]["code"] == "AXIS_DISABLED"
    finally:
        world.loader.axes["slew"].enabled = True


def test_stage_timeout_fails_without_advancing(client: TestClient):
    plan = preview(client).json()
    created = create_task(client, plan["plan_id"])
    world = get_world()
    original_velocity = world.loader.axes["boom_luff"].velocity
    try:
        world.loader.axes["boom_luff"].velocity = 0.0
        snapshot = client.post("/api/simulation/step", json={"dt": 20.0}).json()
        assert snapshot["path_task"]["status"] == "failed"
        assert snapshot["path_task"]["failure_code"] == "STAGE_TIMEOUT"
        task = client.get(f"/api/path-tasks/{created.json()['task_id']}").json()
        assert task["stages"][0]["status"] == "failed"
        assert all(stage["status"] == "pending" for stage in task["stages"][1:])
    finally:
        world.loader.axes["boom_luff"].velocity = original_velocity


def test_reset_cancels_active_task_and_releases_manual_control(client: TestClient):
    plan = preview(client).json()
    created = create_task(client, plan["plan_id"])
    task_id = created.json()["task_id"]
    reset = client.post("/api/simulation/reset")
    assert reset.status_code == 200
    assert reset.json()["path_task"]["status"] == "cancelled"
    task = client.get(f"/api/path-tasks/{task_id}").json()
    assert task["status"] == "cancelled"
    assert task["pause_reason"] == "simulation_reset"
    manual = client.post(
        "/api/axis/travel/target",
        json={"target": 1.0, "velocity": 0.5},
    )
    assert manual.status_code == 200


def test_plan_store_enforces_ttl_and_lru_capacity(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    plan = PathPlan.model_validate(preview(client).json())
    clock = {"value": 0.0}
    monkeypatch.setattr(
        "app.core.path_planning.plan_store.time.monotonic",
        lambda: clock["value"],
    )

    ttl_store = PathPlanStore(max_items=2, ttl_seconds=10.0)
    ttl_store.put(plan)
    clock["value"] = 9.0
    assert ttl_store.get(plan.plan_id).plan_id == plan.plan_id
    clock["value"] = 10.1
    with pytest.raises(PathPlanningError) as expired:
        ttl_store.get(plan.plan_id)
    assert expired.value.code == "PLAN_EXPIRED"

    clock["value"] = 0.0
    lru_store = PathPlanStore(max_items=2, ttl_seconds=100.0)
    first = plan.model_copy(update={"plan_id": "plan-first"})
    second = plan.model_copy(update={"plan_id": "plan-second"})
    third = plan.model_copy(update={"plan_id": "plan-third"})
    lru_store.put(first)
    lru_store.put(second)
    lru_store.get(first.plan_id)
    lru_store.put(third)
    with pytest.raises(PathPlanningError) as evicted:
        lru_store.get(second.plan_id)
    assert evicted.value.code == "PLAN_NOT_FOUND"
    assert lru_store.get(first.plan_id).plan_id == first.plan_id
    assert lru_store.get(third.plan_id).plan_id == third.plan_id


def test_task_history_is_bounded_and_cleans_idempotency_map():
    world = SimulationWorld(create_default_ship_loader())
    scene_state = SceneState(load_scene_config())
    transformer = GridTransformer()
    planner = PathPlanner(
        world,
        scene_state,
        transformer,
        TargetSolver(world.loader.solver),
    )
    store = PathPlanStore()
    manager = PathTaskManager(world, scene_state, store, planner, max_history=200)
    world.attach_path_task_manager(manager)
    assert world.path_task_executor is manager.executor
    target = GridTargetRequest(
        vessel_id="Vessel-R",
        hold_id="R2",
        column=9,
        row=4,
    )

    first_task_id = None
    for index in range(201):
        plan = store.put(planner.preview(target))
        task, created = manager.create_task(f"history-{index}", plan.plan_id)
        assert created is True
        first_task_id = first_task_id or task.task_id
        manager.cancel_task(task.task_id)

    assert len(manager.list_tasks(limit=200)) == 200
    with pytest.raises(PathPlanningError) as evicted:
        manager.get_task(first_task_id)
    assert evicted.value.code == "TASK_NOT_FOUND"

    replacement_plan = store.put(planner.preview(target))
    replacement, created = manager.create_task("history-0", replacement_plan.plan_id)
    assert created is True
    manager.cancel_task(replacement.task_id)
