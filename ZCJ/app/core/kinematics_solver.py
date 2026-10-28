from __future__ import annotations

import math

from app.models.geometry import ShipLoaderGeometry
from app.models.pose import Pose, Vec3
from app.models.snapshot import KinematicsResult
from app.utils.math_utils import normalize_vector, rotation_z


class KinematicsSolver:
    """Forward kinematics solver for the single-loader MVP."""

    def solve(self, geometry: ShipLoaderGeometry, axis_values: dict[str, float]) -> KinematicsResult:
        travel = axis_values.get("travel", 0.0)
        slew = axis_values.get("slew", 0.0)
        boom_luff = axis_values.get("boom_luff", 0.0)
        boom_extension = axis_values.get("boom_extension", 0.0)
        chute_rotate = axis_values.get("chute_rotate", 0.0)

        rail_origin = geometry.rail_origin.to_array()
        rail_direction = geometry.rail_direction.to_array()
        base_position = rail_origin + rail_direction * travel
        base_position = base_position + [0.0, 0.0, geometry.base_height_m]
        slew_center_position = base_position

        slew_rotation = rotation_z(slew)
        boom_root_position = base_position + slew_rotation @ geometry.boom_base_offset.to_array()

        luff_rad = math.radians(boom_luff)
        boom_direction = normalize_vector(slew_rotation @ [0.0, math.cos(luff_rad), math.sin(luff_rad)])
        boom_total_length = geometry.boom_base_length_m + boom_extension
        fixed_boom_tip_position = boom_root_position + boom_direction * geometry.boom_base_length_m
        boom_tip_position = boom_root_position + boom_direction * boom_total_length

        chute_top_position = boom_tip_position
        chute_bottom_position = chute_top_position + [0.0, 0.0, -geometry.chute_length_m]
        discharge_point = chute_bottom_position + geometry.discharge_offset.to_array()

        chute_direction = normalize_vector(rotation_z(slew + chute_rotate) @ [0.0, 1.0, 0.0])

        return KinematicsResult(
            slew_center_position=Vec3.from_array(slew_center_position),
            base_position=Vec3.from_array(base_position),
            boom_root_position=Vec3.from_array(boom_root_position),
            fixed_boom_tip_position=Vec3.from_array(fixed_boom_tip_position),
            boom_tip_position=Vec3.from_array(boom_tip_position),
            chute_top_position=Vec3.from_array(chute_top_position),
            chute_bottom_position=Vec3.from_array(chute_bottom_position),
            discharge_point=Vec3.from_array(discharge_point),
            rail_origin_position=Vec3.from_array(rail_origin),
            rail_direction_point=Vec3.from_array(rail_origin + rail_direction),
            boom_direction=Vec3.from_array(boom_direction),
            chute_direction=Vec3.from_array(chute_direction),
            loader_pose=Pose(
                position=Vec3.from_array(base_position),
                orientation_deg=Vec3(x=0.0, y=0.0, z=slew),
            ),
            boom_pose=Pose(
                position=Vec3.from_array(boom_root_position),
                orientation_deg=Vec3(x=0.0, y=boom_luff, z=slew),
            ),
            chute_pose=Pose(
                position=Vec3.from_array(chute_top_position),
                orientation_deg=Vec3(x=0.0, y=0.0, z=slew + chute_rotate),
            ),
        )
