from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import uuid4

from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.path_task_executor import PathTaskExecutor
from app.core.path_planning.plan_store import PathPlanStore
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.models.path_planning import (
    PathStageExecution,
    PathTask,
    PathTaskSummary,
)
logger = logging.getLogger(__name__)


class PathTaskManager:
    ACTIVE_STATUSES = {"running", "paused"}
    PARTICIPATING_AXES = (
        "travel",
        "slew",
        "boom_luff",
        "boom_extension",
        "chute_rotate",
    )

    def __init__(
        self,
        world: SimulationWorld,
        scene_state: SceneState,
        plan_store: PathPlanStore,
        planner: PathPlanner,
        max_history: int = 200,
    ) -> None:
        self.world = world
        self.scene_state = scene_state
        self.plan_store = plan_store
        self.planner = planner
        self.max_history = max_history
        self._tasks: OrderedDict[str, PathTask] = OrderedDict()
        self._request_map: dict[str, tuple[str, str]] = {}
        self._active_task_id: str | None = None
        self._latest_task_id: str | None = None
        self._stage_issued = False
        self._lock = world.lock
        self.executor = PathTaskExecutor(self)

    def create_task(self, request_id: str, plan_id: str) -> tuple[PathTask, bool]:
        with self._lock:
            loading_manager = getattr(self.world, "loading_task_manager", None)
            if loading_manager is not None:
                loading_manager.ensure_standalone_path_allowed()
            return self._create_task_locked(
                request_id,
                plan_id,
                owner_kind="standalone",
                owner_id=None,
            )

    def create_owned_task(
        self,
        request_id: str,
        plan_id: str,
        *,
        owner_kind: str,
        owner_id: str,
    ) -> tuple[PathTask, bool]:
        with self._lock:
            if owner_kind != "loading":
                raise PathPlanningError(
                    "INVALID_PATH_OWNER",
                    "不支持的路径任务所有者。",
                    status_code=409,
                    context={"owner_kind": owner_kind},
                )
            loading_manager = getattr(self.world, "loading_task_manager", None)
            if (
                loading_manager is None
                or not loading_manager.is_owner_active(owner_id)
            ):
                raise PathPlanningError(
                    "INVALID_PATH_OWNER",
                    "整船装载任务已失去路径控制权。",
                    status_code=409,
                    context={"owner_kind": owner_kind, "owner_id": owner_id},
                )
            return self._create_task_locked(
                request_id,
                plan_id,
                owner_kind="loading",
                owner_id=owner_id,
            )

    def _create_task_locked(
        self,
        request_id: str,
        plan_id: str,
        *,
        owner_kind: str,
        owner_id: str | None,
    ) -> tuple[PathTask, bool]:
        existing = self._request_map.get(request_id)
        if existing is not None:
            existing_plan_id, task_id = existing
            if existing_plan_id != plan_id:
                raise PathPlanningError(
                    "IDEMPOTENCY_CONFLICT",
                    "相同 request_id 不能用于不同的 plan_id。",
                    status_code=409,
                    context={
                        "request_id": request_id,
                        "existing_plan_id": existing_plan_id,
                        "requested_plan_id": plan_id,
                    },
                )
            task = self._tasks[task_id]
            if task.owner_kind != owner_kind or task.owner_id != owner_id:
                raise PathPlanningError(
                    "IDEMPOTENCY_CONFLICT",
                    "相同 request_id 不能用于不同的任务所有者。",
                    status_code=409,
                    context={"request_id": request_id},
                )
            return task.model_copy(deep=True), False
        if self._active_task() is not None:
            raise PathPlanningError(
                "TASK_CONFLICT",
                "已有自动路径任务正在运行或暂停。",
                status_code=409,
                context={"task_id": self._active_task_id},
            )
        plan = self.plan_store.get(plan_id)
        self.planner.validate_for_execution(plan)
        execution_plan = self.planner.refresh_for_execution(plan)
        now = datetime.now(timezone.utc)
        task = PathTask(
            task_id=f"task-{uuid4().hex}",
            request_id=request_id,
            plan_id=plan_id,
            scene_revision=execution_plan.scene_revision,
            status="running",
            current_stage=execution_plan.stages[0].stage,
            stage_index=1,
            created_at=now,
            started_at=now,
            target=execution_plan.target,
            axis_solution=execution_plan.axis_solution,
            stages=[
                PathStageExecution(
                    stage=stage.stage,
                    axis_targets=dict(stage.axis_targets),
                    estimated_duration_s=stage.estimated_duration_s,
                    timeout_s=stage.timeout_s,
                )
                for stage in execution_plan.stages
            ],
            estimated_duration_s=execution_plan.estimated_duration_s,
            owner_kind=owner_kind,
            owner_id=owner_id,
        )
        self._tasks[task.task_id] = task
        self._request_map[request_id] = (plan_id, task.task_id)
        self._active_task_id = task.task_id
        self._latest_task_id = task.task_id
        self._stage_issued = False
        self._trim_history()
        self.world.resume()
        self._log("path_task_started", task)
        return task.model_copy(deep=True), True

    def get_current(self) -> PathTask | None:
        with self._lock:
            task = self._active_task()
            if task is not None:
                self._refresh_live_position_locked(task)
            return None if task is None else task.model_copy(deep=True)

    def get_task(self, task_id: str) -> PathTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise PathPlanningError(
                    "TASK_NOT_FOUND",
                    f"未找到路径任务 {task_id}。",
                    status_code=404,
                    context={"task_id": task_id},
                )
            if task.status in self.ACTIVE_STATUSES:
                self._refresh_live_position_locked(task)
            return task.model_copy(deep=True)

    def list_tasks(self, limit: int = 50) -> list[PathTask]:
        with self._lock:
            values = list(self._tasks.values())[-limit:]
            for task in values:
                if task.status in self.ACTIVE_STATUSES:
                    self._refresh_live_position_locked(task)
            return [task.model_copy(deep=True) for task in reversed(values)]

    def snapshot_summary(self) -> PathTaskSummary | None:
        with self._lock:
            task = self._active_task()
            if task is None and self._latest_task_id is not None:
                task = self._tasks.get(self._latest_task_id)
            if task is None:
                return None
            if task.status in self.ACTIVE_STATUSES:
                self._refresh_live_position_locked(task)
            return PathTaskSummary(
                task_id=task.task_id,
                plan_id=task.plan_id,
                status=task.status,
                current_stage=task.current_stage,
                stage_index=task.stage_index,
                stage_count=task.stage_count,
                target=task.target,
                actual_point=task.actual_point,
                error=task.error,
                pause_reason=task.pause_reason,
                failure_code=task.failure_code,
                owner_kind=task.owner_kind,
                owner_id=task.owner_id,
            )

    def pause_task(
        self,
        task_id: str,
        reason: str = "operator_paused",
        *,
        owner_id: str | None = None,
    ) -> PathTask:
        with self._lock:
            task = self._require_active_task(task_id)
            self._ensure_owner_locked(task, owner_id)
            if task.status == "paused":
                return task.model_copy(deep=True)
            if task.status != "running":
                raise self._invalid_state(task, "pause")
            self._pause_locked(task, reason)
            return task.model_copy(deep=True)

    def resume_task(
        self,
        task_id: str,
        *,
        owner_id: str | None = None,
    ) -> PathTask:
        with self._lock:
            task = self._require_active_task(task_id)
            self._ensure_owner_locked(task, owner_id)
            if task.status != "paused":
                raise self._invalid_state(task, "resume")
            self.planner.validate_task(task)
            task.status = "running"
            task.pause_reason = None
            self._stage_issued = False
            self.world.resume()
            self._log("path_task_resumed", task)
            return task.model_copy(deep=True)

    def cancel_task(
        self,
        task_id: str,
        reason: str = "operator_cancelled",
        *,
        owner_id: str | None = None,
    ) -> PathTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise PathPlanningError(
                    "TASK_NOT_FOUND",
                    f"未找到路径任务 {task_id}。",
                    status_code=404,
                    context={"task_id": task_id},
                )
            self._ensure_owner_locked(task, owner_id)
            if task.status == "cancelled":
                return task.model_copy(deep=True)
            if task.status not in self.ACTIVE_STATUSES:
                raise self._invalid_state(task, "cancel")
            self._stop_axes()
            if self.world.paused:
                self.world.resume()
            task.status = "cancelled"
            task.pause_reason = reason
            task.completed_at = datetime.now(timezone.utc)
            self._active_task_id = None
            self._stage_issued = False
            self._log("path_task_cancelled", task, reason=reason)
            return task.model_copy(deep=True)

    def before_step(self) -> None:
        self.executor.before_step()

    def after_step(self) -> None:
        self.executor.after_step()

    def on_simulation_pause(self) -> None:
        with self._lock:
            task = self._active_task()
            if task is not None and task.status == "running":
                self._pause_locked(task, "simulation_paused")
            else:
                self.world.pause()

    def on_simulation_resume(self) -> None:
        with self._lock:
            task = self._active_task()
            if task is not None and task.status == "paused":
                raise PathPlanningError(
                    "INVALID_TASK_STATE",
                    "自动任务已暂停，请使用任务恢复接口完成重验。",
                    status_code=409,
                    context={"task_id": task.task_id},
                )
            self.world.resume()

    def on_simulation_reset(self) -> None:
        with self._lock:
            task = self._active_task()
            if task is not None:
                self.cancel_task(
                    task.task_id,
                    reason="simulation_reset",
                    owner_id=task.owner_id,
                )

    def ensure_manual_control_allowed(self) -> None:
        with self._lock:
            task = self._active_task()
            if task is not None:
                raise PathPlanningError(
                    "AUTOMATION_LOCKED",
                    "自动路径任务持有运动轴控制权，请先取消任务。",
                    status_code=409,
                    context={"task_id": task.task_id, "status": task.status},
                )

    def on_manual_stop(self) -> None:
        with self._lock:
            task = self._active_task()
            if task is not None and task.status == "running":
                self._pause_locked(task, "manual_stop")

    def ensure_belt_control_allowed(self, running: bool) -> None:
        if not running:
            return
        with self._lock:
            task = self._active_task()
            if task is not None:
                raise PathPlanningError(
                    "PATH_TASK_ACTIVE",
                    "自动路径任务运行或暂停期间不能启动皮带。",
                    status_code=409,
                    context={"task_id": task.task_id},
                )

    def _refresh_live_position_locked(self, task: PathTask) -> None:
        axis_values = {
            axis_id: axis.current
            for axis_id, axis in self.world.loader.axes.items()
        }
        result = self.world.loader.compute_state().kinematics
        task.actual_point = result.discharge_point
        task.error = self.planner.target_solver.measure_error(
            self.world.loader.geometry,
            task.target,
            axis_values,
        )

    def _pause_locked(self, task: PathTask, reason: str) -> None:
        self._stop_axes()
        task.status = "paused"
        task.pause_reason = reason
        self._stage_issued = False
        self.world.pause()
        self._log("path_task_paused", task, reason=reason)

    def _fail_locked(self, task: PathTask, code: str, message: str) -> None:
        self._stop_axes()
        task.status = "failed"
        task.failure_code = code
        task.failure_message = message
        task.completed_at = datetime.now(timezone.utc)
        self._active_task_id = None
        self._stage_issued = False
        self._log("path_task_failed", task, error_code=code)

    def _stop_axes(self) -> None:
        self.executor.stop_axes()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _active_task(self) -> PathTask | None:
        if self._active_task_id is None:
            return None
        task = self._tasks.get(self._active_task_id)
        if task is None or task.status not in self.ACTIVE_STATUSES:
            return None
        return task

    def _require_active_task(self, task_id: str) -> PathTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise PathPlanningError(
                "TASK_NOT_FOUND",
                f"未找到路径任务 {task_id}。",
                status_code=404,
                context={"task_id": task_id},
            )
        if task.task_id != self._active_task_id:
            raise self._invalid_state(task, "control")
        return task

    @staticmethod
    def _ensure_owner_locked(
        task: PathTask,
        owner_id: str | None,
    ) -> None:
        if task.owner_kind == "standalone":
            if owner_id is None:
                return
        elif task.owner_id == owner_id and owner_id is not None:
            return
        raise PathPlanningError(
            "AUTOMATION_LOCKED",
            "该路径任务由整船装载编排器控制。",
            status_code=409,
            context={
                "task_id": task.task_id,
                "owner_kind": task.owner_kind,
                "owner_id": task.owner_id,
            },
        )

    @staticmethod
    def _invalid_state(task: PathTask, action: str) -> PathPlanningError:
        return PathPlanningError(
            "INVALID_TASK_STATE",
            f"任务状态 {task.status} 不允许执行 {action}。",
            status_code=409,
            context={"task_id": task.task_id, "status": task.status, "action": action},
        )

    def _trim_history(self) -> None:
        while len(self._tasks) > self.max_history:
            task_id, task = self._tasks.popitem(last=False)
            self._request_map.pop(task.request_id, None)
            if self._latest_task_id == task_id:
                self._latest_task_id = None

    @staticmethod
    def _log(event: str, task: PathTask, **extra: object) -> None:
        payload = {
            "event": event,
            "task_id": task.task_id,
            "plan_id": task.plan_id,
            "request_id": task.request_id,
            "scene_revision": task.scene_revision,
            "vessel_id": task.target.vessel_id,
            "hold_id": task.target.hold_id,
            "column": task.target.column,
            "row": task.target.row,
            "status": task.status,
            "stage": task.current_stage,
            **extra,
        }
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
