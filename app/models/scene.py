from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.pose import Vec3

VesselSide = Literal["left", "right", "center"]
CoverType = Literal["none", "horizontal", "vertical"]
CoverState = Literal["open", "closed"]


class HoldGridConfig(BaseModel):
    columns: Literal[10] = 10
    rows: Literal[8] = 8
    index_base: Literal[1] = 1
    column_direction: Literal["bow_to_stern"] = "bow_to_stern"
    row_direction: Literal["port_to_starboard"] = "port_to_starboard"


class HatchCoverConfig(BaseModel):
    length_m: float | None = None
    width_m: float | None = None
    thickness_m: float = 0.2

    @field_validator("length_m", "width_m", "thickness_m")
    @classmethod
    def validate_positive(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("cover dimensions must be positive")
        return value


class HoldConfig(BaseModel):
    id: str
    center_offset_m: float = 0.0
    length_m: float
    width_m: float
    fill_level: float = 0.0
    cover: HatchCoverConfig | None = None
    grid: HoldGridConfig = Field(default_factory=HoldGridConfig)
    hatch_plane_offset_z_m: float | None = None
    cover_state: CoverState | None = None

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

    @field_validator("hatch_plane_offset_z_m")
    @classmethod
    def validate_hatch_plane_offset(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("hatch_plane_offset_z_m cannot be negative")
        return value


class VesselConfig(BaseModel):
    id: str
    position: Vec3
    length_m: float
    width_m: float
    height_m: float
    side: VesselSide = "center"
    cover_type: CoverType = "none"
    yaw_deg: float = 0.0
    holds: list[HoldConfig] = Field(default_factory=list)

    @field_validator("length_m", "width_m", "height_m")
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("vessel dimensions must be positive")
        return value


class SceneConfig(BaseModel):
    revision: int = 0
    vessels: list[VesselConfig] = Field(default_factory=list)

    @field_validator("revision")
    @classmethod
    def validate_revision(cls, value: int) -> int:
        if value < 0:
            raise ValueError("revision cannot be negative")
        return value
