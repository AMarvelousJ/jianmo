from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.grid_transformer import GridTransformer
from app.core.path_planning.target_solver import TargetSolver
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.models.path_planning import (
    AxisSolution,
    GridTargetRequest,
    PathPlan,
    PathStagePlan,
    PathTarget,
    PathTask,
)


class PathPlanner:
    SAFE_LUFF_DEG = 24.0
    SAFE_RETRACT_M = 0.0
    PLAN_TTL_SECONDS = 600

    def __init__(
        self,
        world: SimulationWorld,
        scene_state: SceneState,
        transformer: GridTransformer,
        target_solver: TargetSolver,
    ) -> None:
        self.world = world
        self.scene_state = scene_state
        self.transformer = transformer
        self.target_solver = target_solver

    def preview(self, request: GridTargetRequest) -> PathPlan:
        scene = self.scene_state.get_scene()
        self._require_belt_stopped(status_code=409)
        target = self.transformer.target(scene, request)
        vessel, _ = self.transformer.find_vessel_hold(
            scene,
            request.vessel_id,
            request.hold_id,
        )
        solution, verification_error = self.target_solver.solve(
            self.world.loader.geometry,
            self.world.loader.axes,
            vessel,
            target,
        )
        stages = self._build_stages(solution.as_dict(), self._axis_currents())
        created_at = datetime.now(timezone.utc)
        return PathPlan(
            plan_id=f"plan-{uuid4().hex}",
            scene_revision=scene.revision,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self.PLAN_TTL_SECONDS),
            target=target,
            axis_solution=solution,
            stages=stages,
            estimated_duration_s=sum(stage.estimated_duration_s for stage in stages),
            verification_error=verification_error,
        )

    def refresh_for_execution(self, plan: PathPlan) -> PathPlan:
        stages = self._build_stages(plan.axis_solution.as_dict(), self._axis_currents())
        return plan.model_copy(
            update={
                "stages": stages,
                "estimated_duration_s": sum(stage.estimated_duration_s for stage in stages),
            },
            deep=True,
        )

    def validate_for_execution(self, plan: PathPlan) -> None:
        self._validate_execution_state(
            plan.scene_revision,
            plan.target,
            plan.axis_solution,
        )

    def validate_task(self, task: PathTask) -> None:
        self._validate_execution_state(
            task.scene_revision,
            task.target,
            task.axis_solution,
        )
        for stage in task.stages:
            for axis_id, value in stage.axis_targets.items():
                self._validate_axis_target(axis_id, value, status_code=409)

    def _validate_execution_state(
        self,
        scene_revision: int,
        target: PathTarget,
        solution: AxisSolution,
    ) -> None:
        scene = self.scene_state.get_scene()
        if scene.revision != scene_revision:
            raise PathPlanningError(
                "SCENE_REVISION_MISMATCH",
                "场景已变化，请重新规划。",
                status_code=409,
                context={
                    "plan_revision": scene_revision,
                    "current_revision": scene.revision,
                },
            )
        self._require_belt_stopped(status_code=409)
        self.transformer.require_target_config_open(
            scene,
            target.vessel_id,
            target.hold_id,
        )
        for axis_id, value in solution.as_dict().items():
            axis = self.world.loader.axes.get(axis_id)
            if axis is None:
                raise PathPlanningError(
                    "AXIS_NOT_FOUND",
                    f"缺少运动轴 {axis_id}。",
                    status_code=409,
                    context={"axis": axis_id},
                )
            if not axis.enabled:
                raise PathPlanningError(
                    "AXIS_DISABLED",
                    f"运动轴 {axis_id} 已禁用。",
                    status_code=409,
                    context={"axis": axis_id},
                )
            if axis.min_value is not None and value < axis.min_value - axis.tolerance:
                raise PathPlanningError(
                    "AXIS_LIMIT_CHANGED",
                    f"运动轴 {axis_id} 的目标低于当前下限。",
                    status_code=409,
                    context={"axis": axis_id, "required": value, "min": axis.min_value},
                )
            if axis.max_value is not None and value > axis.max_value + axis.tolerance:
                raise PathPlanningError(
                    "AXIS_LIMIT_CHANGED",
                    f"运动轴 {axis_id} 的目标超过当前上限。",
                    status_code=409,
                    context={"axis": axis_id, "required": value, "max": axis.max_value},
                )

    def _build_stages(
        self,
        solution: dict[str, float],
        initial_values: dict[str, float],
    ) -> list[PathStagePlan]:
        specs = [
            ("safe_luff", {"boom_luff": self.SAFE_LUFF_DEG}),
            ("safe_retract", {"boom_extension": self.SAFE_RETRACT_M}),
            ("safe_slew", {"slew": solution["slew"]}),
            ("travel", {"travel": solution["travel"]}),
            ("target_luff", {"boom_luff": solution["boom_luff"]}),
            (
                "final_approach",
                {
                    "boom_extension": solution["boom_extension"],
                    "chute_rotate": solution["chute_rotate"],
                },
            ),
        ]
        current = dict(initial_values)
        stages: list[PathStagePlan] = []
        for stage_name, targets in specs:
            durations = [
                self._axis_duration(axis_id, current[axis_id], target)
                for axis_id, target in targets.items()
            ]
            duration = max(durations, default=0.0)
            stages.append(
                PathStagePlan(
                    stage=stage_name,
                    axis_targets=targets,
                    estimated_duration_s=duration,
                    timeout_s=2.0 * duration + 5.0,
                )
            )
            current.update(targets)
        return stages

    def _axis_duration(self, axis_id: str, current: float, target: float) -> float:
        self._validate_axis_target(axis_id, target, status_code=400)
        axis = self.world.loader.axes[axis_id]
        distance = abs(target - current)
        if distance <= axis.tolerance:
            return 0.0
        if axis.velocity <= 0 or not math.isfinite(axis.velocity):
            raise PathPlanningError(
                "AXIS_SPEED_ZERO",
                f"运动轴 {axis_id} 的速度必须大于 0。",
                context={"axis": axis_id, "velocity": axis.velocity},
            )
        return distance / axis.velocity

    def _validate_axis_target(
        self,
        axis_id: str,
        target: float,
        *,
        status_code: int,
    ) -> None:
        axis = self.world.loader.axes.get(axis_id)
        if axis is None:
            raise PathPlanningError(
                "AXIS_NOT_FOUND",
                f"缺少运动轴 {axis_id}。",
                status_code=status_code,
                context={"axis": axis_id},
            )
        if not axis.enabled:
            raise PathPlanningError(
                "AXIS_DISABLED",
                f"运动轴 {axis_id} 已禁用。",
                status_code=status_code,
                context={"axis": axis_id},
            )
        if axis.min_value is not None and target < axis.min_value - axis.tolerance:
            raise PathPlanningError(
                "SAFE_TARGET_OUT_OF_RANGE",
                f"阶段目标低于运动轴 {axis_id} 下限。",
                status_code=status_code,
                context={"axis": axis_id, "target": target, "min": axis.min_value},
            )
        if axis.max_value is not None and target > axis.max_value + axis.tolerance:
            raise PathPlanningError(
                "SAFE_TARGET_OUT_OF_RANGE",
                f"阶段目标超过运动轴 {axis_id} 上限。",
                status_code=status_code,
                context={"axis": axis_id, "target": target, "max": axis.max_value},
            )

    def _axis_currents(self) -> dict[str, float]:
        return {
            axis_id: axis.current
            for axis_id, axis in self.world.loader.axes.items()
        }

    def _require_belt_stopped(self, *, status_code: int) -> None:
        if self.world.loader.belt.running:
            raise PathPlanningError(
                "BELT_RUNNING",
                "皮带正在运行，请停止皮带后再规划或启动路径。",
                status_code=status_code,
            )
