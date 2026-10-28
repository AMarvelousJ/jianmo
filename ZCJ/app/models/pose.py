from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field, model_serializer, model_validator


class Vec3(BaseModel):
    """JSON-friendly 3D vector used for points and directions."""

    x: float
    y: float
    z: float

    @model_validator(mode="before")
    @classmethod
    def parse_sequence(cls, data: Any) -> Any:
        if isinstance(data, Vec3):
            return data
        if isinstance(data, np.ndarray):
            data = data.tolist()
        if isinstance(data, (list, tuple)):
            if len(data) != 3:
                raise ValueError("Vec3 requires exactly three values")
            return {"x": data[0], "y": data[1], "z": data[2]}
        return data

    @model_serializer(mode="plain")
    def serialize(self) -> list[float]:
        return [self.x, self.y, self.z]

    @classmethod
    def zero(cls) -> "Vec3":
        return cls(x=0.0, y=0.0, z=0.0)

    @classmethod
    def from_array(cls, value: np.ndarray | list[float] | tuple[float, float, float]) -> "Vec3":
        arr = np.asarray(value, dtype=float)
        if arr.shape != (3,):
            raise ValueError("Vec3 array must have shape (3,)")
        return cls(x=float(arr[0]), y=float(arr[1]), z=float(arr[2]))

    def to_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.z]


class Pose(BaseModel):
    position: Vec3
    orientation_deg: Vec3 = Field(default_factory=Vec3.zero)

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "position": self.position.to_list(),
            "orientation_deg": self.orientation_deg.to_list(),
        }

