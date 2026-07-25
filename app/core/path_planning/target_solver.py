from __future__ import annotations

import math

import numpy as np

from app.core.kinematics_solver import KinematicsSolver
from app.core.motion_axis import MotionAxis
from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.grid_transformer import normalize_angle
from app.models.geometry import ShipLoaderGeometry
from app.models.path_planning import AxisSolution, PathTarget, PositionError
from app.models.scene import VesselConfig
from app.utils.math_utils import normalize_vector, rotation_z


class TargetSolver:
    POSITION_TOLERANCE_M = 0.10
    HEADING_TOLERANCE_DEG = 1.0
    GEOMETRY_EPSILON_M = 1e-6

    def __init__(self, forward_solver: KinematicsSolver | None = None) -> None:
        self.forward_solver = forward_solver or KinematicsSolver()

    def solve(
        self,
        geometry: ShipLoaderGeometry,
        axes: dict[str, MotionAxis],
        vessel: VesselConfig,
        target: PathTarget,
    ) -> tuple[AxisSolution, PositionError]:
        slew_target = self._slew_for_side(vessel)
        q = normalize_vector(geometry.rail_direction.to_array())
        u = normalize_vector(rotation_z(slew_target) @ [0.0, 1.0, 0.0])
        z_axis = np.array([0.0, 0.0, 1.0], dtype=float)
        if abs(float(q @ z_axis)) > self.GEOMETRY_EPSILON_M or abs(float(q @ u)) > self.GEOMETRY_EPSILON_M:
            raise PathPlanningError(
                "UNSUPPORTED_GEOMETRY",
                "当前解析求解要求轨道水平且与固定船侧臂架方向正交。",
                context={"rail_dot_up": float(q @ z_axis), "rail_dot_boom": float(q @ u)},
            )

        tip_target = target.world_point.to_array() - (
            np.array([0.0, 0.0, -geometry.chute_length_m], dtype=float)
            + geometry.discharge_offset.to_array()
        )
        root0 = (
            geometry.rail_origin.to_array()
            + np.array([0.0, 0.0, geometry.base_height_m], dtype=float)
            + rotation_z(slew_target) @ geometry.boom_base_offset.to_array()
        )
        delta = tip_target - root0
        travel = float(delta @ q)
        radial = float(delta @ u)
        vertical = float(delta @ z_axis)
        residual = delta - travel * q - radial * u - vertical * z_axis
        residual_norm = float(np.linalg.norm(residual))
        if residual_norm > self.GEOMETRY_EPSILON_M:
            raise PathPlanningError(
                "TARGET_UNREACHABLE",
                "目标点不在当前轨道和船侧回转平面内。",
                context={"orthogonal_residual_m": residual_norm},
            )
        if radial < -self.GEOMETRY_EPSILON_M:
            raise PathPlanningError(
                "TARGET_UNREACHABLE",
                "目标点位于臂架固定船侧方向的后方。",
                context={"radial_m": radial, "slew_deg": slew_target},
            )
        radial = max(0.0, radial)
        boom_total_length = math.hypot(radial, vertical)
        boom_luff = math.degrees(math.atan2(vertical, radial))
        boom_extension = boom_total_length - geometry.boom_base_length_m
        chute_rotate = normalize_angle(target.heading_deg - 90.0 - slew_target)
        solution = AxisSolution(
            travel=travel,
            slew=slew_target,
            boom_luff=boom_luff,
            boom_extension=boom_extension,
            chute_rotate=chute_rotate,
        )
        for axis_id, value in solution.as_dict().items():
            self._validate_axis_value(axes, axis_id, value)

        error = self.measure_error(geometry, target, solution.as_dict())
        if (
            error.horizontal_m > self.POSITION_TOLERANCE_M
            or error.vertical_m > self.POSITION_TOLERANCE_M
            or error.heading_deg > self.HEADING_TOLERANCE_DEG
        ):
            raise PathPlanningError(
                "FORWARD_VERIFICATION_FAILED",
                "解析解未通过正运动学回算。",
                context=error.model_dump(),
            )
        return solution, error

    def measure_error(
        self,
        geometry: ShipLoaderGeometry,
        target: PathTarget,
        axis_values: dict[str, float],
    ) -> PositionError:
        result = self.forward_solver.solve(geometry, axis_values)
        actual = result.discharge_point.to_array()
        expected = target.world_point.to_array()
        heading = math.degrees(
            math.atan2(result.chute_direction.y, result.chute_direction.x)
        )
        return PositionError(
            horizontal_m=float(np.linalg.norm(actual[:2] - expected[:2])),
            vertical_m=abs(float(actual[2] - expected[2])),
            heading_deg=abs(normalize_angle(heading - target.heading_deg)),
        )

    @staticmethod
    def _slew_for_side(vessel: VesselConfig) -> float:
        if vessel.side == "right":
            return 0.0
        if vessel.side == "left":
            return 180.0
        raise PathPlanningError(
            "VESSEL_SIDE_UNSUPPORTED",
            "P0 仅支持 side=left 或 side=right 的船舶。",
            context={"vessel_id": vessel.id, "side": vessel.side},
        )

    @staticmethod
    def _validate_axis_value(
        axes: dict[str, MotionAxis],
        axis_id: str,
        value: float,
    ) -> None:
        axis = axes.get(axis_id)
        if axis is None:
            raise PathPlanningError(
                "AXIS_NOT_FOUND",
                f"缺少运动轴 {axis_id}。",
                context={"axis": axis_id},
            )
        if not math.isfinite(value):
            raise PathPlanningError(
                "TARGET_UNREACHABLE",
                f"运动轴 {axis_id} 的求解值不是有限数。",
                context={"axis": axis_id, "required": value},
            )
        if axis.min_value is not None and value < axis.min_value - axis.tolerance:
            raise PathPlanningError(
                "TARGET_UNREACHABLE",
                f"运动轴 {axis_id} 的目标低于下限。",
                context={
                    "axis": axis_id,
                    "required": value,
                    "min": axis.min_value,
                    "max": axis.max_value,
                },
            )
        if axis.max_value is not None and value > axis.max_value + axis.tolerance:
            raise PathPlanningError(
                "TARGET_UNREACHABLE",
                f"运动轴 {axis_id} 的目标超过上限。",
                context={
                    "axis": axis_id,
                    "required": value,
                    "min": axis.min_value,
                    "max": axis.max_value,
                },
            )
