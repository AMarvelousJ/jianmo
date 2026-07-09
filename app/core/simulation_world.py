from __future__ import annotations

from app.core.ship_loader import ShipLoader
from app.core.vessel_motion import VesselMotion
from app.models.snapshot import SimulationSnapshot


class SimulationWorld:
    def __init__(
        self,
        loader: ShipLoader,
        vessel_motion: VesselMotion | None = None,
        default_dt: float = 0.1,
    ) -> None:
        if default_dt <= 0:
            raise ValueError("default_dt must be positive")
        self.loader = loader
        self.vessel_motion = vessel_motion or VesselMotion()
        self.default_dt = default_dt
        self.sim_time = 0.0
        self.paused = False
        self._initial_axis_values = {
            axis_id: axis.current for axis_id, axis in self.loader.axes.items()
        }

    def step(self, dt: float | None = None) -> SimulationSnapshot:
        actual_dt = self.default_dt if dt is None else dt
        if actual_dt < 0:
            raise ValueError("dt cannot be negative")
        if not self.paused:
            self.loader.update(actual_dt)
            self.sim_time += actual_dt
        return self.get_snapshot()

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def reset(self, initial_state: dict[str, float] | None = None) -> None:
        self.sim_time = 0.0
        self.paused = False
        self.loader.reset_axes(initial_state or self._initial_axis_values)

    def get_snapshot(self) -> SimulationSnapshot:
        loader_state = self.loader.compute_state()
        kinematics = loader_state.kinematics
        return SimulationSnapshot(
            sim_time=self.sim_time,
            loader_id=self.loader.loader_id,
            axis_states=loader_state.axis_states,
            key_points=kinematics.key_points(),
            poses={
                "loader_pose": kinematics.loader_pose,
                "boom_pose": kinematics.boom_pose,
                "chute_pose": kinematics.chute_pose,
            },
            belt_state=loader_state.belt_state,
            vessel_motion=self.vessel_motion.pose_at(self.sim_time),
            warnings=loader_state.warnings,
            constraints=loader_state.constraints,
        )

