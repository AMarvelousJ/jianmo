from __future__ import annotations

from app.models.snapshot import BeltStatus


class BeltState:
    def __init__(self) -> None:
        self.running = False
        self.speed_mps = 0.0

    def start(self, speed: float) -> None:
        if speed < 0:
            raise ValueError("belt speed cannot be negative")
        self.running = True
        self.speed_mps = float(speed)

    def stop(self) -> None:
        self.running = False
        self.speed_mps = 0.0

    def to_status(self) -> BeltStatus:
        return BeltStatus(running=self.running, speed_mps=self.speed_mps)

    def to_dict(self) -> dict[str, float | bool]:
        return self.to_status().model_dump()

