from __future__ import annotations

from pydantic import BaseModel


class AxisTargetCommand(BaseModel):
    target: float
    velocity: float | None = None


class BeltCommand(BaseModel):
    speed: float = 0.0
    running: bool = False


class StepCommand(BaseModel):
    dt: float | None = None

