from __future__ import annotations

import math

from app.models.axis import AxisConfig, AxisState, AxisType


class MotionAxis:
    """Uniform-speed motion axis for the MVP simulation kernel."""

    def __init__(self, config: AxisConfig):
        self.axis_id = config.axis_id
        self.axis_type: AxisType = config.axis_type
        self.current = float(config.current)
        self.target = float(config.target if config.target is not None else config.current)
        self.velocity = float(config.velocity)
        self.enabled = config.enabled
        self.running = config.running
        self.min_value = config.min_value
        self.max_value = config.max_value
        self.tolerance = config.tolerance
        self.positive_direction = config.positive_direction
        self.constraint_result = dict(config.constraint_result)
        self.last_update_time = 0.0
        self.at_target = self._is_at_target()

    def set_target(self, target: float, velocity: float | None = None) -> None:
        self._validate_value(target, "target")
        if velocity is not None:
            if velocity < 0:
                raise ValueError("velocity cannot be negative")
            self.velocity = float(velocity)
        self.target = float(target)
        self.at_target = self._is_at_target()
        self.running = self.enabled and not self.at_target

    def start(self) -> None:
        if not self.enabled:
            self.running = False
            return
        self.at_target = self._is_at_target()
        self.running = not self.at_target

    def stop(self) -> None:
        self.running = False
        self.at_target = self._is_at_target()

    def reset(self, value: float) -> None:
        self._validate_value(value, "value")
        self.current = float(value)
        self.target = float(value)
        self.running = False
        self.at_target = True
        self.last_update_time = 0.0

    def update(self, dt: float) -> None:
        if dt < 0:
            raise ValueError("dt cannot be negative")
        self.last_update_time += dt
        if not self.enabled:
            self.running = False
            return
        if self._is_at_target():
            self.current = self.target
            self.running = False
            self.at_target = True
            return
        if not self.running:
            self.at_target = False
            return
        if self.velocity <= 0 or dt == 0:
            self.at_target = self._is_at_target()
            return

        distance = self.target - self.current
        max_step = self.velocity * dt
        if abs(distance) <= max(self.tolerance, max_step):
            self.current = self.target
            self.running = False
            self.at_target = True
            return

        self.current += math.copysign(max_step, distance)
        self.at_target = self._is_at_target()

    def to_state(self) -> AxisState:
        return AxisState(
            axis_id=self.axis_id,
            axis_type=self.axis_type,
            current=self.current,
            target=self.target,
            velocity=self.velocity,
            enabled=self.enabled,
            running=self.running,
            at_target=self.at_target,
            min_value=self.min_value,
            max_value=self.max_value,
            tolerance=self.tolerance,
            positive_direction=self.positive_direction,
            last_update_time=self.last_update_time,
            constraint_result=self.constraint_result,
        )

    def _validate_value(self, value: float, name: str) -> None:
        if self.min_value is not None and value < self.min_value:
            raise ValueError(f"{name} is below min_value for axis {self.axis_id}")
        if self.max_value is not None and value > self.max_value:
            raise ValueError(f"{name} is above max_value for axis {self.axis_id}")

    def _is_at_target(self) -> bool:
        return abs(self.target - self.current) <= self.tolerance

