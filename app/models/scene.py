from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.pose import Vec3

VesselSide = Literal["left", "right", "center"]


class HoldConfig(BaseModel):
    id: str
    center_offset_m: float = 0.0
    length_m: float
    width_m: float
    fill_level: float = 0.0

    @field_validator("length_m", "width_m")
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("hold dimensions must be positive")
        return value

    @field_validator("fill_level")
    @classmethod
    def validate_fill_level(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("fill_level must be between 0 and 1")
        return value


class VesselConfig(BaseModel):
    id: str
    position: Vec3
    length_m: float
    width_m: float
    height_m: float
    side: VesselSide = "center"
    holds: list[HoldConfig] = Field(default_factory=list)

    @field_validator("length_m", "width_m", "height_m")
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("vessel dimensions must be positive")
        return value


class SceneConfig(BaseModel):
    vessels: list[VesselConfig] = Field(default_factory=list)

