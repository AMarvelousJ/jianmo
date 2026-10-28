from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.loading.errors import LoadingError
from app.core.path_planning.errors import PathPlanningError
from app.models.path_planning import GridTargetRequest

if TYPE_CHECKING:
    from app.core.loading.task_manager import LoadingTaskManager
    from app.models.loading import LoadingTask


class LoadingTaskExecutor:
    """Advance the authoritative whole-vessel loading state machine."""

    def __init__(self, manager: LoadingTaskManager) -> None:
        self.manager = manager

    def before_step(self, base_dt: float) -> None:
        del base_dt
        manager = self.manager
        with manager._lock:
            task = manager._active_task_locked()
            if task is None or task.status == "paused":
                return
            try:
                if task.status in {"positioning", "loading"}:
                    interlock = manager._recoverable_interlock_locked(task)
                    if interlock is not None:
                        reason, code, message = interlock
                        manager._pause_locked(
                            task,
                            reason,
                            code=code,
                            message=message,
                        )
                        return
                if task.status == "positioning":
                    self._before_positioning_locked(task)
                elif task.status == "loading":
                    self._before_loading_locked(task)
            except (LoadingError, PathPlanningError) as error:
                manager._fail_locked(
                    task,
                    getattr(error, "code", "LOADING_INTERNAL_ERROR"),
                    getattr(error, "message", str(error)),
                    source="orchestration",
                )
            except Exception as error:
                manager._fail_locked(
                    task,
                    "LOADING_INTERNAL_ERROR",
                    str(error),
                    source="orchestration",
                )

    def after_step(self, base_dt: float, motion_dt: float) -> None:
        del motion_dt
        manager = self.manager
        with manager._lock:
            task = manager._active_task_locked()
            if task is None or task.status == "paused":
                return
            try:
                task.demo_elapsed_s += base_dt
                if task.status == "positioning":
                    self._after_positioning_locked(task)
                elif task.status == "loading":
                    self._after_loading_locked(task, base_dt)
                elif task.status == "waiting_drainage":
                    self._after_drainage_locked(task, base_dt)
                elif task.status == "verifying":
                    self._verify_locked(task)
            except (LoadingError, PathPlanningError) as error:
                manager._fail_locked(
                    task,
                    getattr(error, "code", "LOADING_INTERNAL_ERROR"),
                    getattr(error, "message", str(error)),
                    source="execution",
                )
            except Exception as error:
                manager._fail_locked(
                    task,
                    "LOADING_INTERNAL_ERROR",
                    str(error),
                    source="execution",
                )

    def _before_positioning_locked(self, task: LoadingTask) -> None:
        manager = self.manager
        if manager.world.loader.belt.running:
            manager.world.loader.set_belt(0.0, False)
            manager._pause_locked(
                task,
                "belt_interlock",
                code="BELT_INTERLOCK_VIOLATION",
                message="定位期间检测到皮带运行。",
            )
            return
        if task.current_path_task_id is not None:
            return

        batch = manager._batch_locked(task)
        plan = manager.path_planner.preview(
            GridTargetRequest(
                vessel_id=manager.plan.vessel_id,
                hold_id=batch.hold_id,
                column=batch.column,
                row=batch.row,
            )
        )
        manager.path_plan_store.put(plan)
        path_task, _ = manager.path_task_manager.create_owned_task(
            request_id=(
                f"loading:{task.task_id}:batch:{batch.batch_no}:"
                f"scene:{task.scene_revision}:plan:{plan.plan_id}"
            ),
            plan_id=plan.plan_id,
            owner_kind="loading",
            owner_id=task.task_id,
        )
        progress = manager._current_batch_progress_locked(task)
        progress.path_task_id = path_task.task_id
        progress.status = "positioning"
        if progress.started_at is None:
            progress.started_at = manager._now()
        task.current_path_task_id = path_task.task_id
        task.current_target_world_point = plan.target.world_point
        task.current_phase = f"path_{path_task.current_stage}"
        manager._emit_locked(
            "loading_path_started",
            task,
            path_task_id=path_task.task_id,
            hold_id=batch.hold_id,
            column=batch.column,
            row=batch.row,
        )

    def _after_positioning_locked(self, task: LoadingTask) -> None:
        manager = self.manager
        if task.current_path_task_id is None:
            return
        path_task = manager.path_task_manager.get_task(
            task.current_path_task_id
        )
        if path_task.status == "running":
            task.current_phase = f"path_{path_task.current_stage}"
            return
        if path_task.status == "paused":
            manager._pause_locked(
                task,
                path_task.pause_reason or "path_paused",
                code=path_task.failure_code,
                message=path_task.failure_message,
            )
            return
        if path_task.status == "arrived":
            interlock = manager._recoverable_interlock_locked(task)
            if interlock is not None:
                reason, code, message = interlock
                manager._pause_locked(
                    task,
                    reason,
                    code=code,
                    message=message,
                )
                return
            task.status = "loading"
            task.current_phase = "belt_starting"
            manager._current_batch_progress_locked(task).status = "loading"
            manager._emit_locked(
                "loading_position_arrived",
                task,
                path_task_id=path_task.task_id,
            )
            return
        manager._fail_locked(
            task,
            path_task.failure_code or "LOADING_PATH_FAILED",
            path_task.failure_message or "从属路径任务未能到达目标。",
            source="path",
        )

    def _before_loading_locked(self, task: LoadingTask) -> None:
        manager = self.manager
        if not manager.world.loader.belt.running:
            if task.current_phase != "belt_starting":
                manager._pause_locked(
                    task,
                    "belt_stopped",
                    code="BELT_INTERLOCK_VIOLATION",
                    message="装载过程中皮带意外停止。",
                )
                return
            manager.world.loader.set_belt(
                manager.plan.belt_speed_mps,
                True,
            )
            task.current_phase = "loading_cargo"
            manager._emit_locked(
                "loading_belt_started",
                task,
                speed_mps=manager.plan.belt_speed_mps,
            )
            return
        if (
            abs(
                manager.world.loader.belt.speed_mps
                - manager.plan.belt_speed_mps
            )
            > 1e-9
        ):
            raise LoadingError(
                "BELT_SPEED_MISMATCH",
                "皮带速度与配载计划不一致。",
                status_code=409,
                context={
                    "expected": manager.plan.belt_speed_mps,
                    "actual": manager.world.loader.belt.speed_mps,
                },
            )

    def _after_loading_locked(
        self,
        task: LoadingTask,
        base_dt: float,
    ) -> None:
        manager = self.manager
        if not manager.world.loader.belt.running:
            manager._pause_locked(
                task,
                "belt_stopped",
                code="BELT_INTERLOCK_VIOLATION",
                message="装载过程中皮带意外停止。",
            )
            return
        batch = manager._batch_locked(task)
        progress = manager._current_batch_progress_locked(task)
        remaining = progress.target_kg - progress.loaded_kg
        increment = manager.rate_model.increment_kg(
            task_id=task.task_id,
            batch_no=batch.batch_no,
            rate_tph=manager.plan.nominal_rate_tph,
            loading_scale=task.loading_scale,
            base_dt=base_dt,
            remaining_kg=remaining,
        )
        progress.loaded_kg += increment
        task.logical_business_s += (
            increment * 3600.0 / (manager.plan.nominal_rate_tph * 1000.0)
        )
        manager._recalculate_totals_locked(task)
        if progress.loaded_kg > progress.target_kg:
            raise LoadingError(
                "TONNAGE_INVARIANT_BROKEN",
                "批次装载吨位超过目标。",
                status_code=500,
                context={
                    "batch_no": batch.batch_no,
                    "loaded_kg": progress.loaded_kg,
                    "target_kg": progress.target_kg,
                },
            )
        manager._emit_progress_if_due_locked(task)
        if progress.loaded_kg < progress.target_kg:
            return

        progress.loaded_kg = progress.target_kg
        progress.status = "completed"
        progress.completed_at = manager._now()
        manager._recalculate_totals_locked(task)
        manager.world.loader.set_belt(0.0, False)
        manager._emit_locked("loading_belt_stopped", task)
        manager._emit_locked("loading_batch_completed", task)

        if batch.batch_no == 5:
            task.status = "waiting_drainage"
            task.current_phase = "drainage_wait"
            task.current_path_task_id = None
            task.current_target_world_point = None
            task.drainage_elapsed_demo_s = 0.0
            task.drainage_remaining_demo_s = (
                manager.plan.execution.drainage_demo_s
            )
            manager._emit_locked("loading_drainage_started", task)
            return
        if batch.batch_no == len(manager.plan.batches()):
            task.status = "verifying"
            task.current_phase = "final_verification"
            manager._emit_locked("loading_verification_started", task)
            return
        self._advance_batch_locked(task)

    def _after_drainage_locked(
        self,
        task: LoadingTask,
        base_dt: float,
    ) -> None:
        manager = self.manager
        moving_axes = [
            axis_id
            for axis_id, axis in manager.world.loader.axes.items()
            if axis.running
        ]
        if manager.world.loader.belt.running or moving_axes:
            manager._fail_locked(
                task,
                "DRAINAGE_INTERLOCK_VIOLATION",
                "排水等待期间设备必须保持停止。",
                source="drainage_interlock",
            )
            return
        config = manager.plan.execution
        previous_elapsed = task.drainage_elapsed_demo_s
        task.drainage_elapsed_demo_s = min(
            config.drainage_demo_s,
            task.drainage_elapsed_demo_s + base_dt,
        )
        task.drainage_remaining_demo_s = max(
            0.0,
            config.drainage_demo_s - task.drainage_elapsed_demo_s,
        )
        task.logical_business_s += (
            task.drainage_elapsed_demo_s - previous_elapsed
        ) * (
            config.drainage_logical_s / config.drainage_demo_s
        )
        manager._emit_progress_if_due_locked(task)
        if task.drainage_remaining_demo_s > 1e-9:
            return
        manager._emit_locked("loading_drainage_completed", task)
        self._advance_batch_locked(task)

    def _advance_batch_locked(self, task: LoadingTask) -> None:
        manager = self.manager
        if task.current_batch_no is None:
            raise LoadingError(
                "LOADING_INTERNAL_ERROR",
                "推进批次时缺少当前批次。",
                status_code=500,
            )
        task.current_batch_no += 1
        next_progress = manager._current_batch_progress_locked(task)
        task.current_round_no = next_progress.round_no
        task.status = "positioning"
        task.current_phase = "path_planning"
        task.current_path_task_id = None
        task.current_target_world_point = None
        next_progress.status = "positioning"
        manager._emit_locked("loading_batch_positioning", task)

    def _verify_locked(self, task: LoadingTask) -> None:
        manager = self.manager
        manager._recalculate_totals_locked(task)
        batch_valid = all(
            item.loaded_kg == item.target_kg
            and item.status == "completed"
            for item in task.batch_progress
        )
        hold_valid = all(
            item.loaded_kg == item.target_kg for item in task.hold_progress
        )
        round_valid = all(
            item.loaded_kg == item.target_kg for item in task.round_progress
        )
        total_valid = task.loaded_total_kg == manager.plan.total_target_kg
        if not (batch_valid and hold_valid and round_valid and total_valid):
            manager._fail_locked(
                task,
                "TONNAGE_INVARIANT_BROKEN",
                "最终批次、货舱、轮次或整船吨位核对失败。",
                source="verification",
            )
            return
        manager._complete_locked(task)
