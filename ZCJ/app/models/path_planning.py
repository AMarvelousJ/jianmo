from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.pose import Vec3

PathStageName = Literal[
    "safe_luff",
    "safe_retract",
    "safe_slew",
    "travel",
    "target_luff",
    "final_approach",
]
PathTaskStatus = Literal["ready", "running", "paused", "arrived", "cancelled", "failed"]
StageExecutionStatus = Literal["pending", "running", "completed", "skipped", "failed"]


class GridTargetRequest(BaseModel):
    vessel_id: str
    hold_id: str
    column: int
    row: int
    loading_clearance_m: float = 1.0
    chute_heading_deg: float | None = None


class PathTaskCreateRequest(BaseModel):
    request_id: str
    plan_id: str

    @field_validator("request_id", "plan_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class GridCell(BaseModel):
    column: int
    row: int
    local_center_m: Vec3
    world_center_m: Vec3


class HoldGridResponse(BaseModel):
    vessel_id: str
    hold_id: str
    scene_revision: int
    columns: int = 10
    rows: int = 8
    index_base: int = 1
    column_direction: str = "bow_to_stern"
    row_direction: str = "port_to_starboard"
    cell_length_m: float
    cell_width_m: float
    cells: list[GridCell]


class PathTarget(BaseModel):
    vessel_id: str
    hold_id: str
    column: int
    row: int
    hold_local_point: Vec3
    world_point: Vec3
    heading_deg: float
    loading_clearance_m: float


class AxisSolution(BaseModel):
    travel: float
    slew: float
    boom_luff: float
    boom_extension: float
    chute_rotate: float

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class PositionError(BaseModel):
    horizontal_m: float
    vertical_m: float
    heading_deg: float


class PathStagePlan(BaseModel):
    stage: PathStageName
    axis_targets: dict[str, float]
    estimated_duration_s: float
    timeout_s: float


class PathPlan(BaseModel):
    plan_id: str
    scene_revision: int
    created_at: datetime
    expires_at: datetime
    target: PathTarget
    feasible: Literal[True] = True
    axis_solution: AxisSolution
    stages: list[PathStagePlan]
    estimated_duration_s: float
    verification_error: PositionError
    warnings: list[str] = Field(default_factory=list)


class PathStageExecution(BaseModel):
    stage: PathStageName
    status: StageExecutionStatus = "pending"
    axis_targets: dict[str, float]
    estimated_duration_s: float
    timeout_s: float
    started_at_sim_s: float | None = None
    completed_at_sim_s: float | None = None
    elapsed_s: float | None = None


class PathTask(BaseModel):
    task_id: str
    request_id: str
    plan_id: str
    scene_revision: int
    status: PathTaskStatus
    current_stage: PathStageName | None = None
    stage_index: int = 0
    stage_count: int = 6
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    target: PathTarget
    axis_solution: AxisSolution
    stages: list[PathStageExecution]
    estimated_duration_s: float
    pause_reason: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    actual_point: Vec3 | None = None
    error: PositionError | None = None
    owner_kind: Literal["standalone", "loading"] = "standalone"
    owner_id: str | None = None


class PathTaskSummary(BaseModel):
    task_id: str
    plan_id: str
    status: PathTaskStatus
    current_stage: PathStageName | None
    stage_index: int
    stage_count: int = 6
    target: PathTarget
    actual_point: Vec3 | None = None
    error: PositionError | None = None
    pause_reason: str | None = None
    failure_code: str | None = None
    owner_kind: Literal["standalone", "loading"] = "standalone"
    owner_id: str | None = None
