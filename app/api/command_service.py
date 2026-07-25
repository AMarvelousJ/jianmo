from __future__ import annotations

from app.core.simulation_world import SimulationWorld
from app.models.snapshot import SimulationSnapshot


class MotionCommandService:
    def __init__(self, world: SimulationWorld):
        self.world = world

    def set_axis_target(self, axis_id: str, target: float, velocity: float | None = None) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.ensure_manual_control_allowed()
            self.world.loader.set_axis_target(axis_id, target, velocity)
            return self.world.get_snapshot()

    def start_axis(self, axis_id: str) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.ensure_manual_control_allowed()
            self.world.loader.start_axis(axis_id)
            return self.world.get_snapshot()

    def stop_axis(self, axis_id: str) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.on_manual_stop()
            self.world.loader.stop_axis(axis_id)
            return self.world.get_snapshot()

    def set_belt(self, speed: float, running: bool) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.ensure_belt_control_allowed(running)
            self.world.loader.set_belt(speed, running)
            return self.world.get_snapshot()

    def pause_simulation(self) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.on_simulation_pause()
            else:
                self.world.pause()
            return self.world.get_snapshot()

    def resume_simulation(self) -> SimulationSnapshot:
        with self.world.lock:
            if self.world.path_task_manager is not None:
                self.world.path_task_manager.on_simulation_resume()
            else:
                self.world.resume()
            return self.world.get_snapshot()

    def reset_simulation(self, initial_state: dict[str, float] | None = None) -> SimulationSnapshot:
        with self.world.lock:
            self.world.reset(initial_state)
            return self.world.get_snapshot()

    def step_simulation(self, dt: float | None = None) -> SimulationSnapshot:
        return self.world.step(dt)
