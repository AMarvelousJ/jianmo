from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AxisType = Literal["linear", "rotary", "binary"]


class AxisConfig(BaseModel):
    axis_id: str
    axis_type: AxisType
    current: float = 0.0
    target: float | None = None
    velocity: float = 1.0
    max_velocity: float | None = None
    enabled: bool = True
    running: bool = False
    min_value: float | None = None
    max_value: float | None = None
    tolerance: float = 1e-3
    positive_direction: int = 1
    constraint_result: dict[str, Any] = Field(default_factory=dict)

    @field_validator("velocity")
    @classmethod
    def validate_velocity(cls, value: float) -> float:
        if value < 0:
            raise ValueError("velocity cannot be negative")
        return value

    @field_validator("max_velocity")
    @classmethod
    def validate_max_velocity(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("max_velocity cannot be negative")
        return value

    @field_validator("tolerance")
    @classmethod
    def validate_tolerance(cls, value: float) -> float:
        if value < 0:
            raise ValueError("tolerance cannot be negative")
        return value

    @model_validator(mode="after")
    def validate_limits(self) -> "AxisConfig":
        if self.target is None:
            self.target = self.current
        if self.max_velocity is None:
            self.max_velocity = self.velocity
        if self.velocity > self.max_velocity:
            raise ValueError("velocity cannot exceed max_velocity")
        if self.min_value is not None and self.max_value is not None:
            if self.max_value < self.min_value:
                raise ValueError("max_value cannot be less than min_value")
        for field_name in ("current", "target"):
            value = getattr(self, field_name)
            if self.min_value is not None and value < self.min_value:
                raise ValueError(f"{field_name} is below min_value")
            if self.max_value is not None and value > self.max_value:
                raise ValueError(f"{field_name} is above max_value")
        return self


class AxisState(BaseModel):
    axis_id: str
    axis_type: AxisType
    current: float
    target: float
    velocity: float
    max_velocity: float | None = None
    enabled: bool
    running: bool
    at_target: bool
    min_value: float | None = None
    max_value: float | None = None
    tolerance: float = 1e-3
    positive_direction: int = 1
    last_update_time: float = 0.0
    constraint_result: dict[str, Any] = Field(default_factory=dict)
