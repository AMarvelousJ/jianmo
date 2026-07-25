from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.path_planning.errors import PathPlanningError
from app.models.path_planning import PathTask

if TYPE_CHECKING:
    from app.core.path_planning.task_manager import PathTaskManager


class PathTaskExecutor:
    """Advance one path task using the world's simulation clock."""

    def __init__(self, manager: PathTaskManager) -> None:
        self.manager = manager

    def before_step(self) -> None:
        manager = self.manager
        with manager._lock:
            task = manager._active_task()
            if task is None or task.status != "running":
                return
            try:
                manager.planner.validate_task(task)
            except PathPlanningError as error:
                if error.code == "SCENE_REVISION_MISMATCH":
                    manager._pause_locked(task, "scene_changed")
                else:
                    manager._fail_locked(task, error.code, error.message)
                return
            stage = task.stages[task.stage_index - 1]
            if manager._stage_issued:
                return
            try:
                for axis_id, target in stage.axis_targets.items():
                    manager.world.loader.set_axis_target(axis_id, target)
            except (KeyError, ValueError) as error:
                manager._fail_locked(task, "AXIS_TARGET_REJECTED", str(error))
                return
            if stage.started_at_sim_s is None:
                stage.started_at_sim_s = manager.world.sim_time
            stage.status = "running"
            manager._stage_issued = True
            manager._log(
                "path_stage_started",
                task,
                stage=stage.stage,
                axis_targets=stage.axis_targets,
            )

    def after_step(self) -> None:
        manager = self.manager
        with manager._lock:
            task = manager._active_task()
            if task is None or task.status != "running" or not manager._stage_issued:
                return
            stage = task.stages[task.stage_index - 1]
            started = (
                stage.started_at_sim_s
                if stage.started_at_sim_s is not None
                else manager.world.sim_time
            )
            elapsed = manager.world.sim_time - started
            at_target = all(
                manager.world.loader.axes[axis_id].at_target
                for axis_id in stage.axis_targets
            )
            if not at_target and elapsed > stage.timeout_s:
                stage.status = "failed"
                stage.elapsed_s = elapsed
                manager._fail_locked(
                    task,
                    "STAGE_TIMEOUT",
                    f"阶段 {stage.stage} 运行超时。",
                )
                return
            if not at_target:
                return
            stage.status = "skipped" if stage.estimated_duration_s == 0 else "completed"
            stage.completed_at_sim_s = manager.world.sim_time
            stage.elapsed_s = elapsed
            manager._log(
                "path_stage_skipped" if stage.status == "skipped" else "path_stage_completed",
                task,
                stage=stage.stage,
                elapsed_s=elapsed,
            )
            if task.stage_index >= task.stage_count:
                self._verify_locked(task)
                return
            task.stage_index += 1
            task.current_stage = task.stages[task.stage_index - 1].stage
            manager._stage_issued = False

    def stop_axes(self) -> None:
        for axis_id in self.manager.PARTICIPATING_AXES:
            self.manager.world.loader.stop_axis(axis_id)

    def _verify_locked(self, task: PathTask) -> None:
        manager = self.manager
        axis_values = {
            axis_id: axis.current
            for axis_id, axis in manager.world.loader.axes.items()
        }
        result = manager.world.loader.compute_state().kinematics
        error = manager.planner.target_solver.measure_error(
            manager.world.loader.geometry,
            task.target,
            axis_values,
        )
        task.actual_point = result.discharge_point
        task.error = error
        task.current_stage = None
        task.completed_at = manager._now()
        if (
            error.horizontal_m
            <= manager.planner.target_solver.POSITION_TOLERANCE_M
            and error.vertical_m
            <= manager.planner.target_solver.POSITION_TOLERANCE_M
            and error.heading_deg
            <= manager.planner.target_solver.HEADING_TOLERANCE_DEG
        ):
            task.status = "arrived"
            manager._log("path_task_arrived", task, error=error.model_dump())
        else:
            task.status = "failed"
            task.failure_code = "FINAL_POSITION_ERROR"
            task.failure_message = "最终定位误差超过允许范围。"
            manager._log("path_task_failed", task, error=error.model_dump())
        manager._active_task_id = None
        manager._stage_issued = False
