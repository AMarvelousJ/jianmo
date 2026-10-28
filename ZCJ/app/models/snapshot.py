from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.axis import AxisState
from app.models.loading import LoadingTaskSummary
from app.models.path_planning import PathTaskSummary
from app.models.pose import Pose, Vec3


class KinematicsResult(BaseModel):
    slew_center_position: Vec3
    base_position: Vec3
    boom_root_position: Vec3
    fixed_boom_tip_position: Vec3
    boom_tip_position: Vec3
    chute_top_position: Vec3
    chute_bottom_position: Vec3
    discharge_point: Vec3
    rail_origin_position: Vec3
    rail_direction_point: Vec3
    boom_direction: Vec3
    chute_direction: Vec3
    loader_pose: Pose
    boom_pose: Pose
    chute_pose: Pose

    def key_points(self) -> dict[str, Vec3]:
        return {
            "slew_center_position": self.slew_center_position,
            "base_position": self.base_position,
            "boom_root_position": self.boom_root_position,
            "fixed_boom_tip_position": self.fixed_boom_tip_position,
            "boom_tip_position": self.boom_tip_position,
            "chute_top_position": self.chute_top_position,
            "chute_bottom_position": self.chute_bottom_position,
            "discharge_point": self.discharge_point,
            "rail_origin_position": self.rail_origin_position,
            "rail_direction_point": self.rail_direction_point,
            "boom_direction": self.boom_direction,
            "chute_direction": self.chute_direction,
        }


class BeltStatus(BaseModel):
    running: bool = False
    speed_mps: float = 0.0


class VesselPose(BaseModel):
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    used_for_discharge_coordinate: bool = False


class ShipLoaderState(BaseModel):
    loader_id: str
    axis_states: dict[str, AxisState]
    kinematics: KinematicsResult
    belt_state: BeltStatus
    warnings: list[str] = Field(default_factory=list)
    constraints: dict[str, object] = Field(default_factory=dict)


class SimulationSnapshot(BaseModel):
    sim_time: float
    sim_paused: bool
    loader_id: str
    axis_states: dict[str, AxisState]
    key_points: dict[str, Vec3]
    poses: dict[str, Pose]
    belt_state: BeltStatus
    vessel_motion: VesselPose
    warnings: list[str] = Field(default_factory=list)
    constraints: dict[str, object] = Field(default_factory=dict)
    path_task: PathTaskSummary | None = None
    loading_task: LoadingTaskSummary | None = None
