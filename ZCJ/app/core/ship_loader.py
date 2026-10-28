from __future__ import annotations

from app.core.belt_state import BeltState
from app.core.kinematics_solver import KinematicsSolver
from app.core.motion_axis import MotionAxis
from app.models.axis import AxisConfig, AxisState
from app.models.geometry import ShipLoaderGeometry
from app.models.snapshot import ShipLoaderState


class ShipLoader:
    def __init__(
        self,
        loader_id: str,
        geometry: ShipLoaderGeometry,
        axis_configs: dict[str, AxisConfig],
        solver: KinematicsSolver | None = None,
    ) -> None:
        self.loader_id = loader_id
        self.geometry = geometry
        self.axes = {axis_id: MotionAxis(config) for axis_id, config in axis_configs.items()}
        self.solver = solver or KinematicsSolver()
        self.belt = BeltState()

    def update(self, dt: float) -> None:
        for axis in self.axes.values():
            axis.update(dt)

    def set_axis_target(self, axis_id: str, target: float, velocity: float | None = None) -> None:
        self._axis(axis_id).set_target(target, velocity)

    def start_axis(self, axis_id: str) -> None:
        self._axis(axis_id).start()

    def stop_axis(self, axis_id: str) -> None:
        self._axis(axis_id).stop()

    def set_belt(self, speed: float, running: bool) -> None:
        if running:
            self.belt.start(speed)
        else:
            self.belt.stop()

    def reset_axes(self, values: dict[str, float] | None = None) -> None:
        values = values or {}
        for axis_id, axis in self.axes.items():
            axis.reset(values.get(axis_id, axis.current))
        self.belt.stop()

    def compute_state(self) -> ShipLoaderState:
        axis_states = self.axis_states()
        axis_values = {axis_id: state.current for axis_id, state in axis_states.items()}
        kinematics = self.solver.solve(self.geometry, axis_values)
        return ShipLoaderState(
            loader_id=self.loader_id,
            axis_states=axis_states,
            kinematics=kinematics,
            belt_state=self.belt.to_status(),
        )

    def axis_states(self) -> dict[str, AxisState]:
        return {axis_id: axis.to_state() for axis_id, axis in self.axes.items()}

    def _axis(self, axis_id: str) -> MotionAxis:
        if axis_id not in self.axes:
            raise KeyError(f"unknown axis_id: {axis_id}")
        return self.axes[axis_id]

