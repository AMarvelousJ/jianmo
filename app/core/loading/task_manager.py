from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import uuid4

from app.core.loading.errors import LoadingError
from app.core.loading.event_store import LoadingEventStore
from app.core.loading.plan_validator import LoadingPlanValidator
from app.core.loading.rate_model import LoadingRateModel
from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.plan_store import PathPlanStore
from app.core.path_planning.task_manager import PathTaskManager
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.models.loading import (
    LoadingBatch,
    LoadingBatchProgress,
    LoadingEvent,
    LoadingHoldProgress,
    LoadingPlan,
    LoadingPlanValidation,
    LoadingRoundProgress,
    LoadingTask,
    LoadingTaskCreateRequest,
    LoadingTaskSummary,
)

logger = logging.getLogger(__name__)


class LoadingTaskManager:
    ACTIVE_STATUSES = {
        "prechecking",
        "positioning",
        "loading",
        "waiting_drainage",
        "paused",
        "verifying",
    }
    TERMINAL_STATUSES = {"completed", "cancelled", "failed"}

    def __init__(
        self,
        world: SimulationWorld,
        scene_state: SceneState,
        plan: LoadingPlan,
        validator: LoadingPlanValidator,
        path_planner: PathPlanner,
        path_plan_store: PathPlanStore,
        path_task_manager: PathTaskManager,
        *,
        max_history: int = 50,
    ) -> None:
        from app.core.loading.task_executor import LoadingTaskExecutor

        self.world = world
        self.scene_state = scene_state
        self.plan = plan
        self.validator = validator
        self.path_planner = path_planner
        self.path_plan_store = path_plan_store
        self.path_task_manager = path_task_manager
        self.max_history = max_history
        self.event_store = LoadingEventStore()
        self.rate_model = LoadingRateModel()
        self._tasks: OrderedDict[str, LoadingTask] = OrderedDict()
        self._request_map: dict[str, tuple[str, str]] = {}
        self._current_task_id: str | None = None
        self._last_progress_event_s: dict[str, float] = {}
        self._wall_started_monotonic: dict[str, float] = {}
        self._lock = world.lock
        self.executor = LoadingTaskExecutor(self)

    def get_plan(self, plan_id: str | None = None) -> LoadingPlan:
        if plan_id is not None and plan_id != self.plan.plan_id:
            raise LoadingError(
                "LOADING_PLAN_NOT_FOUND",
                f"未找到配载计划 {plan_id}。",
                status_code=404,
                context={"plan_id": plan_id},
            )
        return self.plan.model_copy(deep=True)

    def validate_plan(
        self,
        plan_id: str | None = None,
        *,
        check_paths: bool = True,
    ) -> LoadingPlanValidation:
        plan = self.get_plan(plan_id)
        return self.validator.validate(plan, check_paths=check_paths)

    def create_task(
        self,
        request: LoadingTaskCreateRequest,
    ) -> tuple[LoadingTask, bool]:
        with self._lock:
            existing = self._request_map.get(request.request_id)
            if existing is not None:
                existing_plan_id, task_id = existing
                if existing_plan_id != request.plan_id:
                    raise LoadingError(
                        "IDEMPOTENCY_CONFLICT",
                        "相同 request_id 不能用于不同的配载计划。",
                        status_code=409,
                        context={
                            "request_id": request.request_id,
                            "existing_plan_id": existing_plan_id,
                            "requested_plan_id": request.plan_id,
                        },
                    )
                task = self._tasks[task_id]
                self._refresh_wall_elapsed_locked(task)
                return task.model_copy(deep=True), False
            if request.plan_id != self.plan.plan_id:
                self.get_plan(request.plan_id)

            active = self._active_task_locked()
            if active is not None:
                raise LoadingError(
                    "LOADING_TASK_CONFLICT",
                    "已有整船装载任务正在运行或暂停。",
                    status_code=409,
                    context={"task_id": active.task_id, "status": active.status},
                )

            validation = self.validator.validate(self.plan, check_paths=True)
            now = self._now()
            task = self._new_task(request, validation.scene_revision, now)
            self._tasks[task.task_id] = task
            self._wall_started_monotonic[task.task_id] = time.monotonic()
            self._request_map[request.request_id] = (
                request.plan_id,
                task.task_id,
            )
            self._current_task_id = task.task_id
            self._trim_history_locked()
            self._emit_locked("loading_task_created", task)

            if not validation.valid:
                task.status = "failed"
                task.current_phase = "precheck_failed"
                task.failure_code = "LOADING_PRECHECK_FAILED"
                task.failure_message = "配载计划或场景预检查失败。"
                task.failure_source = "precheck"
                task.completed_at = self._now()
                self._refresh_wall_elapsed_locked(task, terminal=True)
                self._emit_locked(
                    "loading_task_failed",
                    task,
                    errors=[item.model_dump() for item in validation.errors],
                )
                raise LoadingError(
                    "LOADING_PRECHECK_FAILED",
                    task.failure_message,
                    status_code=409,
                    context={
                        "task_id": task.task_id,
                        "errors": [
                            item.model_dump() for item in validation.errors
                        ],
                    },
                )

            task.status = "positioning"
            task.current_phase = "path_planning"
            task.started_at = now
            task.batch_progress[0].status = "positioning"
            self.world.resume()
            self._emit_locked("loading_precheck_passed", task)
            self._emit_locked("loading_batch_positioning", task)
            return task.model_copy(deep=True), True

    def get_current(self) -> LoadingTask | None:
        with self._lock:
            task = self._current_task_locked()
            if task is not None:
                self._refresh_wall_elapsed_locked(task)
            return None if task is None else task.model_copy(deep=True)

    def get_task(self, task_id: str) -> LoadingTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise LoadingError(
                    "LOADING_TASK_NOT_FOUND",
                    f"未找到整船装载任务 {task_id}。",
                    status_code=404,
                    context={"task_id": task_id},
                )
            self._refresh_wall_elapsed_locked(task)
            return task.model_copy(deep=True)

    def list_tasks(self, limit: int = 50) -> list[LoadingTask]:
        with self._lock:
            tasks = list(self._tasks.values())[-limit:]
            for task in tasks:
                self._refresh_wall_elapsed_locked(task)
            return [task.model_copy(deep=True) for task in reversed(tasks)]

    def list_events(
        self,
        task_id: str,
        *,
        event_type: str | None = None,
        round_no: int | None = None,
        batch_no: int | None = None,
    ) -> list[LoadingEvent]:
        with self._lock:
            if task_id not in self._tasks:
                self.get_task(task_id)
            return self.event_store.list(
                task_id,
                event_type=event_type,
                round_no=round_no,
                batch_no=batch_no,
            )

    def snapshot_summary(self) -> LoadingTaskSummary | None:
        with self._lock:
            task = self._current_task_locked()
            if task is None:
                return None
            self._refresh_wall_elapsed_locked(task)
            return LoadingTaskSummary(
                task_id=task.task_id,
                plan_id=task.plan_id,
                status=task.status,
                mode=task.mode,
                current_round_no=task.current_round_no,
                current_batch_no=task.current_batch_no,
                current_phase=task.current_phase,
                current_path_task_id=task.current_path_task_id,
                current_target_world_point=task.current_target_world_point,
                loaded_total_kg=task.loaded_total_kg,
                target_total_kg=task.target_total_kg,
                batch_progress=[
                    item.model_copy(deep=True) for item in task.batch_progress
                ],
                hold_progress=[
                    item.model_copy(deep=True) for item in task.hold_progress
                ],
                round_progress=[
                    item.model_copy(deep=True) for item in task.round_progress
                ],
                demo_elapsed_s=task.demo_elapsed_s,
                wall_elapsed_s=task.wall_elapsed_s,
                logical_business_s=task.logical_business_s,
                drainage_elapsed_demo_s=task.drainage_elapsed_demo_s,
                drainage_remaining_demo_s=task.drainage_remaining_demo_s,
                motion_scale=task.motion_scale,
                loading_scale=task.loading_scale,
                pause_reason=task.pause_reason,
                failure_code=task.failure_code,
                failure_message=task.failure_message,
            )

    def pause_task(
        self,
        task_id: str,
        reason: str = "operator_paused",
    ) -> LoadingTask:
        with self._lock:
            task = self._require_current_locked(task_id)
            if task.status == "paused":
                return task.model_copy(deep=True)
            if task.status not in self.ACTIVE_STATUSES:
                raise self._invalid_state(task, "pause")
            self._pause_locked(task, reason)
            return task.model_copy(deep=True)

    def resume_task(self, task_id: str) -> LoadingTask:
        with self._lock:
            task = self._require_current_locked(task_id)
            if task.status != "paused":
                raise self._invalid_state(task, "resume")

            validation = self.validator.validate(self.plan, check_paths=True)
            if not validation.valid:
                first = validation.errors[0]
                task.failure_code = first.code
                task.failure_message = first.message
                raise LoadingError(
                    first.code,
                    first.message,
                    status_code=409,
                    context={
                        "task_id": task.task_id,
                        "errors": [
                            item.model_dump() for item in validation.errors
                        ],
                    },
                )

            previous = task.paused_from_status or "positioning"
            revision_changed = task.scene_revision != validation.scene_revision
            if revision_changed:
                self._cancel_child_path_locked(task, "loading_revalidate")
                task.scene_revision = validation.scene_revision
                task.current_path_task_id = None
                task.current_target_world_point = None
                if previous in {"positioning", "loading"}:
                    previous = "positioning"
                    self._current_batch_progress_locked(task).status = "positioning"

            if previous == "positioning" and task.current_path_task_id is not None:
                path_task = self.path_task_manager.get_task(
                    task.current_path_task_id
                )
                if path_task.status == "paused":
                    self.path_task_manager.resume_task(
                        path_task.task_id,
                        owner_id=task.task_id,
                    )

            task.status = previous
            task.current_phase = (
                "belt_starting"
                if previous == "loading"
                else self._phase_for_status(previous)
            )
            task.paused_from_status = None
            task.pause_reason = None
            task.failure_code = None
            task.failure_message = None
            task.failure_source = None
            self.world.resume()
            self._emit_locked("loading_task_resumed", task)
            return task.model_copy(deep=True)

    def cancel_task(
        self,
        task_id: str,
        reason: str = "operator_cancelled",
    ) -> LoadingTask:
        with self._lock:
            task = self._require_current_locked(task_id)
            if task.status == "cancelled":
                return task.model_copy(deep=True)
            if task.status not in self.ACTIVE_STATUSES:
                raise self._invalid_state(task, "cancel")
            self._cancel_child_path_locked(task, reason)
            self._stop_all_locked()
            task.status = "cancelled"
            task.current_phase = "cancelled"
            task.pause_reason = reason
            task.completed_at = self._now()
            self._refresh_wall_elapsed_locked(task, terminal=True)
            self.world.resume()
            self._emit_locked("loading_task_cancelled", task, reason=reason)
            return task.model_copy(deep=True)

    def reset_task(self, task_id: str) -> LoadingTask:
        with self._lock:
            task = self._require_current_locked(task_id)
            if task.status not in self.TERMINAL_STATUSES:
                raise self._invalid_state(task, "reset")
            self._stop_all_locked()
            self.rate_model.clear_task(task.task_id)
            self._last_progress_event_s.pop(task.task_id, None)
            self._current_task_id = None
            self._log("loading_task_reset", task)
            return task.model_copy(deep=True)

    def before_step(self, base_dt: float) -> None:
        self.executor.before_step(base_dt)

    def after_step(self, base_dt: float, motion_dt: float) -> None:
        self.executor.after_step(base_dt, motion_dt)

    def motion_scale(self) -> float:
        with self._lock:
            task = self._active_task_locked()
            if task is None or task.status != "positioning":
                return 1.0
            return task.motion_scale

    def has_active_task(self) -> bool:
        with self._lock:
            return self._active_task_locked() is not None

    def ensure_standalone_path_allowed(self) -> None:
        with self._lock:
            task = self._active_task_locked()
            if task is not None:
                raise LoadingError(
                    "LOADING_TASK_ACTIVE",
                    "整船装载任务活动期间不能创建公共路径任务。",
                    status_code=409,
                    context={"task_id": task.task_id, "status": task.status},
                )

    def ensure_manual_control_allowed(self) -> None:
        with self._lock:
            task = self._active_task_locked()
            if task is not None:
                raise LoadingError(
                    "AUTOMATION_LOCKED",
                    "整船装载任务持有设备控制权，请先终止任务。",
                    status_code=409,
                    context={"task_id": task.task_id, "status": task.status},
                )

    def ensure_belt_control_allowed(self, running: bool) -> None:
        if not running:
            return
        self.ensure_manual_control_allowed()

    def on_manual_stop(self) -> None:
        with self._lock:
            task = self._active_task_locked()
            if task is not None and task.status != "paused":
                self._pause_locked(task, "manual_stop")

    def on_simulation_pause(self) -> None:
        with self._lock:
            task = self._active_task_locked()
            if task is not None:
                self._pause_locked(task, "simulation_paused")
            else:
                self.world.pause()

    def on_simulation_resume(self) -> None:
        with self._lock:
            task = self._active_task_locked()
            if task is not None and task.status == "paused":
                raise LoadingError(
                    "INVALID_LOADING_TASK_STATE",
                    "整船装载任务已暂停，请使用装船任务恢复接口。",
                    status_code=409,
                    context={"task_id": task.task_id},
                )
            self.world.resume()

    def on_simulation_reset(self) -> None:
        with self._lock:
            task = self._current_task_locked()
            if task is not None and task.status in self.ACTIVE_STATUSES:
                self.cancel_task(task.task_id, reason="simulation_reset")
            if task is not None:
                self.rate_model.clear_task(task.task_id)
                self._last_progress_event_s.pop(task.task_id, None)
            self._current_task_id = None

    def is_owner_active(self, owner_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(owner_id)
            return (
                task is not None
                and task.task_id == self._current_task_id
                and task.status in self.ACTIVE_STATUSES
            )

    def _new_task(
        self,
        request: LoadingTaskCreateRequest,
        scene_revision: int,
        now: datetime,
    ) -> LoadingTask:
        batch_progress: list[LoadingBatchProgress] = []
        for round_ in self.plan.rounds:
            for batch in round_.batches:
                batch_progress.append(
                    LoadingBatchProgress(
                        batch_no=batch.batch_no,
                        round_no=round_.round_no,
                        hold_no=batch.hold_no,
                        hold_id=batch.hold_id,
                        target_kg=batch.target_kg,
                        column=batch.column,
                        row=batch.row,
                    )
                )
        holds = []
        for hold_no, hold_id in self.plan.hold_mapping.items():
            holds.append(
                LoadingHoldProgress(
                    hold_no=hold_no,
                    hold_id=hold_id,
                    target_kg=sum(
                        batch.target_kg
                        for batch in self.plan.batches()
                        if batch.hold_id == hold_id
                    ),
                )
            )
        rounds = [
            LoadingRoundProgress(
                round_no=round_.round_no,
                target_kg=round_.target_kg,
            )
            for round_ in self.plan.rounds
        ]
        execution = self.plan.execution
        return LoadingTask(
            task_id=f"loading-{uuid4().hex}",
            request_id=request.request_id,
            plan_id=request.plan_id,
            scene_revision=scene_revision,
            mode=request.mode,
            status="prechecking",
            current_round_no=1,
            current_batch_no=1,
            current_phase="validate",
            batch_progress=batch_progress,
            hold_progress=holds,
            round_progress=rounds,
            drainage_remaining_demo_s=execution.drainage_demo_s,
            motion_scale=(
                execution.demo_motion_scale
                if request.mode == "demo"
                else execution.normal_motion_scale
            ),
            loading_scale=(
                execution.demo_loading_scale
                if request.mode == "demo"
                else execution.normal_loading_scale
            ),
            created_at=now,
        )

    def _current_task_locked(self) -> LoadingTask | None:
        if self._current_task_id is None:
            return None
        return self._tasks.get(self._current_task_id)

    def _active_task_locked(self) -> LoadingTask | None:
        task = self._current_task_locked()
        if task is None or task.status not in self.ACTIVE_STATUSES:
            return None
        return task

    def _require_current_locked(self, task_id: str) -> LoadingTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise LoadingError(
                "LOADING_TASK_NOT_FOUND",
                f"未找到整船装载任务 {task_id}。",
                status_code=404,
                context={"task_id": task_id},
            )
        if task.task_id != self._current_task_id:
            raise self._invalid_state(task, "control")
        return task

    def _batch_locked(self, task: LoadingTask) -> LoadingBatch:
        if task.current_batch_no is None:
            raise LoadingError(
                "LOADING_INTERNAL_ERROR",
                "活动任务缺少当前批次。",
                status_code=500,
                context={"task_id": task.task_id},
            )
        return self.plan.batches()[task.current_batch_no - 1]

    def _current_batch_progress_locked(
        self,
        task: LoadingTask,
    ) -> LoadingBatchProgress:
        if task.current_batch_no is None:
            raise LoadingError(
                "LOADING_INTERNAL_ERROR",
                "活动任务缺少当前批次进度。",
                status_code=500,
                context={"task_id": task.task_id},
            )
        return task.batch_progress[task.current_batch_no - 1]

    def _hold_progress_locked(
        self,
        task: LoadingTask,
        hold_id: str,
    ) -> LoadingHoldProgress:
        return next(item for item in task.hold_progress if item.hold_id == hold_id)

    def _round_progress_locked(
        self,
        task: LoadingTask,
        round_no: int,
    ) -> LoadingRoundProgress:
        return next(item for item in task.round_progress if item.round_no == round_no)

    def _pause_locked(
        self,
        task: LoadingTask,
        reason: str,
        *,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        if task.status == "paused":
            return
        previous = task.status
        if task.current_path_task_id is not None:
            try:
                path_task = self.path_task_manager.get_task(
                    task.current_path_task_id
                )
                if path_task.status == "running":
                    self.path_task_manager.pause_task(
                        path_task.task_id,
                        reason=reason,
                        owner_id=task.task_id,
                    )
            except PathPlanningError:
                pass
        self._stop_all_locked()
        task.paused_from_status = previous
        task.status = "paused"
        task.current_phase = "paused"
        task.pause_reason = reason
        task.failure_code = code
        task.failure_message = message
        task.failure_source = "interlock" if code else None
        self.world.pause()
        self._emit_locked(
            "loading_task_paused",
            task,
            reason=reason,
            error_code=code,
        )

    def _fail_locked(
        self,
        task: LoadingTask,
        code: str,
        message: str,
        *,
        source: str,
    ) -> None:
        self._cancel_child_path_locked(task, "loading_failed")
        self._stop_all_locked()
        progress = self._current_batch_progress_locked(task)
        if progress.status != "completed":
            progress.status = "failed"
        task.status = "failed"
        task.current_phase = "failed"
        task.failure_code = code
        task.failure_message = message
        task.failure_source = source
        task.completed_at = self._now()
        self._refresh_wall_elapsed_locked(task, terminal=True)
        self.world.resume()
        self._emit_locked(
            "loading_task_failed",
            task,
            error_code=code,
            error_source=source,
        )

    def _complete_locked(self, task: LoadingTask) -> None:
        self._stop_all_locked()
        task.status = "completed"
        task.current_phase = "completed"
        task.completed_at = self._now()
        self._refresh_wall_elapsed_locked(task, terminal=True)
        self.rate_model.clear_task(task.task_id)
        self._emit_locked("loading_task_completed", task)

    def _cancel_child_path_locked(self, task: LoadingTask, reason: str) -> None:
        if task.current_path_task_id is None:
            return
        try:
            path_task = self.path_task_manager.get_task(task.current_path_task_id)
            if path_task.status in self.path_task_manager.ACTIVE_STATUSES:
                self.path_task_manager.cancel_task(
                    path_task.task_id,
                    reason=reason,
                    owner_id=task.task_id,
                )
        except PathPlanningError:
            pass

    def _stop_all_locked(self) -> None:
        self.world.loader.set_belt(0.0, False)
        for axis in self.world.loader.axes.values():
            axis.stop()

    def _recoverable_interlock_locked(
        self,
        task: LoadingTask,
    ) -> tuple[str, str, str] | None:
        scene = self.scene_state.get_scene()
        batch = self._batch_locked(task)
        vessel = next(
            (item for item in scene.vessels if item.id == self.plan.vessel_id),
            None,
        )
        hold = (
            next((item for item in vessel.holds if item.id == batch.hold_id), None)
            if vessel is not None
            else None
        )
        if hold is None:
            return (
                "hold_missing",
                "LOADING_HOLD_NOT_FOUND",
                f"场景中不存在货舱 {batch.hold_id}。",
            )
        if hold.cover_state != "open":
            return (
                "hatch_cover_closed",
                "HATCH_COVER_CLOSED",
                f"货舱 {batch.hold_id} 舱盖未打开。",
            )
        if scene.revision != task.scene_revision:
            return (
                "scene_changed",
                "SCENE_REVISION_MISMATCH",
                "场景版本已变化，请重新校验后恢复。",
            )
        return None

    def _recalculate_totals_locked(self, task: LoadingTask) -> None:
        task.loaded_total_kg = sum(item.loaded_kg for item in task.batch_progress)
        for hold in task.hold_progress:
            hold.loaded_kg = sum(
                item.loaded_kg
                for item in task.batch_progress
                if item.hold_id == hold.hold_id
            )
        for round_ in task.round_progress:
            round_.loaded_kg = sum(
                item.loaded_kg
                for item in task.batch_progress
                if item.round_no == round_.round_no
            )

    def _emit_progress_if_due_locked(self, task: LoadingTask) -> None:
        last = self._last_progress_event_s.get(task.task_id, -1e9)
        if (
            task.demo_elapsed_s - last
            < self.plan.execution.event_interval_demo_s
        ):
            return
        self._last_progress_event_s[task.task_id] = task.demo_elapsed_s
        self._emit_locked("tonnage_updated", task)

    def _emit_locked(
        self,
        event_type: str,
        task: LoadingTask,
        **details: object,
    ) -> LoadingEvent:
        batch_progress = (
            self._current_batch_progress_locked(task)
            if task.current_batch_no is not None
            else None
        )
        hold_progress = (
            self._hold_progress_locked(task, batch_progress.hold_id)
            if batch_progress is not None
            else None
        )
        event = self.event_store.append(
            LoadingEvent(
                event_id=0,
                event_type=event_type,
                task_id=task.task_id,
                plan_id=task.plan_id,
                scene_revision=task.scene_revision,
                round_no=task.current_round_no,
                batch_no=task.current_batch_no,
                hold_id=(
                    batch_progress.hold_id if batch_progress is not None else None
                ),
                status=task.status,
                phase=task.current_phase,
                sim_time=self.world.sim_time,
                demo_elapsed_s=task.demo_elapsed_s,
                logical_business_s=task.logical_business_s,
                loaded_batch_kg=(
                    batch_progress.loaded_kg
                    if batch_progress is not None
                    else 0
                ),
                loaded_hold_kg=(
                    hold_progress.loaded_kg if hold_progress is not None else 0
                ),
                loaded_total_kg=task.loaded_total_kg,
                details=details,
                created_at=self._now(),
            )
        )
        self._log(event_type, task, **details)
        return event

    def _trim_history_locked(self) -> None:
        while len(self._tasks) > self.max_history:
            task_id, task = self._tasks.popitem(last=False)
            self._request_map.pop(task.request_id, None)
            self.event_store.delete(task_id)
            self._wall_started_monotonic.pop(task_id, None)

    def _refresh_wall_elapsed_locked(
        self,
        task: LoadingTask,
        *,
        terminal: bool = False,
    ) -> None:
        started = self._wall_started_monotonic.get(task.task_id)
        if started is None:
            return
        if task.status not in self.TERMINAL_STATUSES or terminal:
            task.wall_elapsed_s = max(0.0, time.monotonic() - started)
        if terminal:
            self._wall_started_monotonic.pop(task.task_id, None)

    @staticmethod
    def _phase_for_status(status: str) -> str:
        return {
            "positioning": "path_planning",
            "loading": "loading_cargo",
            "waiting_drainage": "drainage_wait",
            "verifying": "final_verification",
        }.get(status, status)

    @staticmethod
    def _invalid_state(task: LoadingTask, action: str) -> LoadingError:
        return LoadingError(
            "INVALID_LOADING_TASK_STATE",
            f"任务状态 {task.status} 不允许执行 {action}。",
            status_code=409,
            context={
                "task_id": task.task_id,
                "status": task.status,
                "action": action,
            },
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _log(event: str, task: LoadingTask, **extra: object) -> None:
        payload = {
            "event": event,
            "task_id": task.task_id,
            "plan_id": task.plan_id,
            "request_id": task.request_id,
            "scene_revision": task.scene_revision,
            "round_no": task.current_round_no,
            "batch_no": task.current_batch_no,
            "status": task.status,
            "phase": task.current_phase,
            "loaded_total_kg": task.loaded_total_kg,
            **extra,
        }
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
