from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.pose import Vec3


class ShipLoaderGeometry(BaseModel):
    rail_origin: Vec3
    rail_direction: Vec3
    base_height_m: float
    boom_base_offset: Vec3
    boom_base_length_m: float
    boom_extension_min_m: float = 0.0
    boom_extension_max_m: float = 0.0
    chute_length_m: float
    discharge_offset: Vec3 = Field(default_factory=lambda: Vec3(x=0.0, y=0.0, z=-0.5))
    visual_scale: float = 1.0

    @field_validator(
        "base_height_m",
        "boom_base_length_m",
        "boom_extension_min_m",
        "boom_extension_max_m",
        "chute_length_m",
        "visual_scale",
    )
    @classmethod
    def validate_non_negative(cls, value: float, info):
        if value < 0:
            raise ValueError(f"{info.field_name} cannot be negative")
        return value

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "ShipLoaderGeometry":
        rail = self.rail_direction.to_array()
        norm = float((rail @ rail) ** 0.5)
        if norm == 0:
            raise ValueError("rail_direction cannot be a zero vector")
        self.rail_direction = Vec3.from_array(rail / norm)
        if self.boom_extension_max_m < self.boom_extension_min_m:
            raise ValueError("boom_extension_max_m cannot be less than boom_extension_min_m")
        return self

