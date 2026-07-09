from __future__ import annotations

from app.core.simulation_world import SimulationWorld
from app.models.axis import AxisState
from app.models.pose import Vec3
from app.models.snapshot import SimulationSnapshot


class SimulationStateService:
    def __init__(self, world: SimulationWorld):
        self.world = world

    def get_snapshot(self) -> SimulationSnapshot:
        return self.world.get_snapshot()

    def get_axis_states(self) -> dict[str, AxisState]:
        return self.world.get_snapshot().axis_states

    def get_key_points(self) -> dict[str, Vec3]:
        return self.world.get_snapshot().key_points

    def get_trajectory(self) -> list[dict]:
        return []

