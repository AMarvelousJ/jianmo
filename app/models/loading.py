from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.pose import Vec3

LoadingMode = Literal["demo", "normal"]
LoadingTaskStatus = Literal[
    "prechecking",
    "positioning",
    "loading",
    "waiting_drainage",
    "paused",
    "verifying",
    "completed",
    "cancelled",
    "failed",
]
LoadingBatchStatus = Literal["pending", "positioning", "loading", "completed", "failed"]
LoadingZone = Literal["center_forward", "center", "center_aft", "trim"]


class LoadingWait(BaseModel):
    type: Literal["drainage"]
    logical_duration_s: float
    demo_duration_s: float

    @field_validator("logical_duration_s", "demo_duration_s")
    @classmethod
    def validate_positive_duration(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("wait duration must be positive")
        return value


class LoadingBatch(BaseModel):
    batch_no: int = Field(ge=1)
    hold_no: str
    hold_id: str
    target_kg: int = Field(gt=0)
    column: int = Field(ge=1, le=10)
    row: int = Field(ge=1, le=8)
    loading_zone: LoadingZone

    @computed_field
    @property
    def target_t(self) -> float:
        return self.target_kg / 1000.0


class LoadingRound(BaseModel):
    round_no: int = Field(ge=1)
    target_kg: int = Field(gt=0)
    batches: list[LoadingBatch]
    after_round_wait: LoadingWait | None = None

    @computed_field
    @property
    def target_t(self) -> float:
        return self.target_kg / 1000.0


class LoadingExecutionConfig(BaseModel):
    demo_motion_scale: float = 12.0
    normal_motion_scale: float = 1.0
    demo_loading_scale: float = 600.0
    normal_loading_scale: float = 1.0
    drainage_logical_s: float = 50400.0
    drainage_demo_s: float = 14.0
    event_interval_demo_s: float = 1.0

    @field_validator(
        "demo_motion_scale",
        "normal_motion_scale",
        "demo_loading_scale",
        "normal_loading_scale",
        "drainage_logical_s",
        "drainage_demo_s",
        "event_interval_demo_s",
    )
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("execution values must be positive")
        return value


class LoadingPlan(BaseModel):
    schema_version: str = "1.0"
    plan_id: str
    name: str
    vessel_id: str
    vessel_name: str
    voyage_no: str
    plan_date: str
    cargo: str
    loading_port: str
    discharge_port: str
    total_target_kg: int = Field(gt=0)
    nominal_rate_tph: float = Field(gt=0)
    belt_speed_mps: float = Field(gt=0)
    hold_mapping: dict[str, str]
    hold_capacity_m3: dict[str, float] = Field(default_factory=dict)
    execution: LoadingExecutionConfig
    rounds: list[LoadingRound]

    @computed_field
    @property
    def total_target_t(self) -> float:
        return self.total_target_kg / 1000.0

    def batches(self) -> list[LoadingBatch]:
        return [batch for round_ in self.rounds for batch in round_.batches]


class LoadingValidationIssue(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class LoadingPathCheck(BaseModel):
    batch_no: int
    hold_id: str
    column: int
    row: int
    feasible: bool
    estimated_duration_s: float | None = None
    error_code: str | None = None
    message: str | None = None


class LoadingPlanValidation(BaseModel):
    valid: bool
    scene_revision: int
    calculated_total_kg: int
    round_totals_kg: dict[int, int]
    hold_totals_kg: dict[str, int]
    errors: list[LoadingValidationIssue] = Field(default_factory=list)
    warnings: list[LoadingValidationIssue] = Field(default_factory=list)
    path_checks: list[LoadingPathCheck] = Field(default_factory=list)


class LoadingPlanEnvelope(BaseModel):
    plan: LoadingPlan
    validation: LoadingPlanValidation


class LoadingBatchProgress(BaseModel):
    batch_no: int
    round_no: int
    hold_no: str
    hold_id: str
    target_kg: int
    loaded_kg: int = 0
    status: LoadingBatchStatus = "pending"
    column: int
    row: int
    path_task_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @computed_field
    @property
    def target_t(self) -> float:
        return self.target_kg / 1000.0

    @computed_field
    @property
    def loaded_t(self) -> float:
        return self.loaded_kg / 1000.0

    @computed_field
    @property
    def progress(self) -> float:
        return min(1.0, self.loaded_kg / self.target_kg)


class LoadingHoldProgress(BaseModel):
    hold_no: str
    hold_id: str
    target_kg: int
    loaded_kg: int = 0

    @computed_field
    @property
    def target_t(self) -> float:
        return self.target_kg / 1000.0

    @computed_field
    @property
    def loaded_t(self) -> float:
        return self.loaded_kg / 1000.0

    @computed_field
    @property
    def progress(self) -> float:
        return min(1.0, self.loaded_kg / self.target_kg)


class LoadingRoundProgress(BaseModel):
    round_no: int
    target_kg: int
    loaded_kg: int = 0

    @computed_field
    @property
    def target_t(self) -> float:
        return self.target_kg / 1000.0

    @computed_field
    @property
    def loaded_t(self) -> float:
        return self.loaded_kg / 1000.0

    @computed_field
    @property
    def progress(self) -> float:
        return min(1.0, self.loaded_kg / self.target_kg)


class LoadingTaskCreateRequest(BaseModel):
    request_id: str
    plan_id: str
    mode: LoadingMode = "demo"

    @field_validator("request_id", "plan_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class LoadingTask(BaseModel):
    task_id: str
    request_id: str
    plan_id: str
    scene_revision: int
    mode: LoadingMode
    status: LoadingTaskStatus
    current_round_no: int | None = None
    current_batch_no: int | None = None
    current_phase: str = "validate"
    current_path_task_id: str | None = None
    current_target_world_point: Vec3 | None = None
    loaded_total_kg: int = 0
    batch_progress: list[LoadingBatchProgress]
    hold_progress: list[LoadingHoldProgress]
    round_progress: list[LoadingRoundProgress]
    demo_elapsed_s: float = 0.0
    wall_elapsed_s: float = 0.0
    logical_business_s: float = 0.0
    drainage_elapsed_demo_s: float = 0.0
    drainage_remaining_demo_s: float = 0.0
    motion_scale: float = 1.0
    loading_scale: float = 1.0
    paused_from_status: str | None = None
    pause_reason: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    failure_source: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @computed_field
    @property
    def loaded_total_t(self) -> float:
        return self.loaded_total_kg / 1000.0

    @computed_field
    @property
    def target_total_kg(self) -> int:
        return sum(item.target_kg for item in self.hold_progress)

    @computed_field
    @property
    def target_total_t(self) -> float:
        return self.target_total_kg / 1000.0

    @computed_field
    @property
    def progress(self) -> float:
        target = self.target_total_kg
        return 0.0 if target <= 0 else min(1.0, self.loaded_total_kg / target)


class LoadingTaskSummary(BaseModel):
    task_id: str
    plan_id: str
    status: LoadingTaskStatus
    mode: LoadingMode
    current_round_no: int | None
    current_batch_no: int | None
    current_phase: str
    current_path_task_id: str | None
    current_target_world_point: Vec3 | None
    loaded_total_kg: int
    target_total_kg: int
    batch_progress: list[LoadingBatchProgress]
    hold_progress: list[LoadingHoldProgress]
    round_progress: list[LoadingRoundProgress]
    demo_elapsed_s: float
    wall_elapsed_s: float
    logical_business_s: float
    drainage_elapsed_demo_s: float
    drainage_remaining_demo_s: float
    motion_scale: float
    loading_scale: float
    pause_reason: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @computed_field
    @property
    def loaded_total_t(self) -> float:
        return self.loaded_total_kg / 1000.0

    @computed_field
    @property
    def target_total_t(self) -> float:
        return self.target_total_kg / 1000.0

    @computed_field
    @property
    def progress(self) -> float:
        return 0.0 if self.target_total_kg <= 0 else min(
            1.0,
            self.loaded_total_kg / self.target_total_kg,
        )


class LoadingEvent(BaseModel):
    event_id: int
    event_type: str
    task_id: str
    plan_id: str
    scene_revision: int
    round_no: int | None = None
    batch_no: int | None = None
    hold_id: str | None = None
    status: str
    phase: str
    sim_time: float
    demo_elapsed_s: float
    logical_business_s: float
    loaded_batch_kg: int = 0
    loaded_hold_kg: int = 0
    loaded_total_kg: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LoadingResetResponse(BaseModel):
    task: LoadingTask
    snapshot: dict[str, Any]
