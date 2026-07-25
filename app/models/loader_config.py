from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.axis import AxisConfig
from app.models.geometry import ShipLoaderGeometry


class LoaderEngineering(BaseModel):
    rated_capacity_tph: float = Field(gt=0)
    max_capacity_tph: float = Field(gt=0)
    rail_gauge_m: float = Field(gt=0)
    wheel_base_m: float = Field(gt=0)
    outreach_min_m: float = Field(gt=0)
    outreach_max_m: float = Field(gt=0)
    boom_extension_travel_m: float = Field(gt=0)
    boom_luff_min_deg: float
    boom_luff_max_deg: float
    boom_slew_min_deg: float
    boom_slew_max_deg: float
    boom_extension_max_speed_mps: float = Field(gt=0)
    boom_slew_max_speed_degps: float = Field(gt=0)
    travel_max_speed_mps: float = Field(gt=0)
    chute_rotation_range_deg: float = Field(gt=0)
    chute_max_speed_degps: float = Field(gt=0)
    belt_width_m: float = Field(gt=0)
    belt_speed_mps: float = Field(gt=0)
    max_wheel_load_kn: float = Field(gt=0)


class LoaderVisualConfig(BaseModel):
    model_mode: Literal["procedural", "glb"] = "procedural"
    asset_revision: str
    material_preset: str = "industrial-neutral"
    portal_height_m: float = Field(gt=0)
    portal_top_length_m: float = Field(gt=0)
    portal_top_width_m: float = Field(gt=0)
    boom_truss_width_m: float = Field(gt=0)
    boom_truss_height_m: float = Field(gt=0)
    telescopic_overlap_m: float = Field(gt=0)
    chute_segments: int = Field(ge=1, le=12)
    chute_top_platform_width_m: float = Field(gt=0)
    chute_top_platform_depth_m: float = Field(gt=0)
    chute_trunk_radius_m: float = Field(gt=0)
    chute_guide_frame_width_m: float = Field(gt=0)
    chute_lower_platform_width_m: float = Field(gt=0)
    chute_lower_platform_depth_m: float = Field(gt=0)
    chute_branch_length_m: float = Field(gt=0)
    chute_branch_spread_m: float = Field(gt=0)
    chute_ladder_rungs: int = Field(ge=4, le=48)
    show_maintenance_details: bool = True


class LoaderProfile(BaseModel):
    schema_version: str
    loader_id: str
    variant_id: Literal["SL15"]
    coordinate_system: Literal["WORLD_Z_UP_METERS"]
    engineering: LoaderEngineering
    geometry: ShipLoaderGeometry
    visual: LoaderVisualConfig
    axes: dict[str, AxisConfig]
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sl15_contract(self) -> "LoaderProfile":
        engineering = self.engineering
        geometry = self.geometry
        extension_travel = geometry.boom_extension_max_m - geometry.boom_extension_min_m
        if abs(extension_travel - engineering.boom_extension_travel_m) > 1e-6:
            raise ValueError("kinematic extension range must match SL15 extension travel")

        required_axes = {"travel", "slew", "boom_luff", "boom_extension", "chute_rotate"}
        if set(self.axes) != required_axes:
            raise ValueError(f"axes must be exactly {sorted(required_axes)}")

        expected_limits = {
            "slew": (engineering.boom_slew_min_deg, engineering.boom_slew_max_deg),
            "boom_luff": (engineering.boom_luff_min_deg, engineering.boom_luff_max_deg),
            "boom_extension": (geometry.boom_extension_min_m, geometry.boom_extension_max_m),
        }
        for axis_id, (expected_min, expected_max) in expected_limits.items():
            axis = self.axes[axis_id]
            if axis.min_value != expected_min or axis.max_value != expected_max:
                raise ValueError(f"{axis_id} limits must match the SL15 engineering profile")

        speed_limits = {
            "travel": engineering.travel_max_speed_mps,
            "slew": engineering.boom_slew_max_speed_degps,
            "boom_extension": engineering.boom_extension_max_speed_mps,
            "chute_rotate": engineering.chute_max_speed_degps,
        }
        for axis_id, maximum in speed_limits.items():
            axis = self.axes[axis_id]
            if axis.max_velocity is None or abs(axis.max_velocity - maximum) > 1e-9:
                raise ValueError(f"{axis_id} max_velocity must match the SL15 engineering profile")

        if engineering.max_capacity_tph < engineering.rated_capacity_tph:
            raise ValueError("max_capacity_tph cannot be below rated_capacity_tph")
        if engineering.outreach_max_m <= engineering.outreach_min_m:
            raise ValueError("outreach_max_m must be greater than outreach_min_m")
        return self
