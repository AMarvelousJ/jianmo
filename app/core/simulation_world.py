from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from app.core.ship_loader import ShipLoader
from app.core.vessel_motion import VesselMotion
from app.models.snapshot import SimulationSnapshot

if TYPE_CHECKING:
    from app.core.path_planning.path_task_executor import PathTaskExecutor
    from app.core.path_planning.task_manager import PathTaskManager


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
        self.lock = threading.RLock()
        self.path_task_manager: PathTaskManager | None = None
        self.path_task_executor: PathTaskExecutor | None = None
        self._initial_axis_values = {
            axis_id: axis.current for axis_id, axis in self.loader.axes.items()
        }

    def step(self, dt: float | None = None) -> SimulationSnapshot:
        with self.lock:
            actual_dt = self.default_dt if dt is None else dt
            if actual_dt < 0:
                raise ValueError("dt cannot be negative")
            if not self.paused:
                if self.path_task_executor is not None:
                    self.path_task_executor.before_step()
                if not self.paused:
                    self.loader.update(actual_dt)
                    self.sim_time += actual_dt
                    if self.path_task_executor is not None:
                        self.path_task_executor.after_step()
            return self.get_snapshot()

    def pause(self) -> None:
        with self.lock:
            self.paused = True

    def resume(self) -> None:
        with self.lock:
            self.paused = False

    def reset(self, initial_state: dict[str, float] | None = None) -> None:
        with self.lock:
            if self.path_task_manager is not None:
                self.path_task_manager.on_simulation_reset()
            self.sim_time = 0.0
            self.paused = False
            self.loader.reset_axes(initial_state or self._initial_axis_values)

    def attach_path_task_manager(self, manager: PathTaskManager) -> None:
        with self.lock:
            self.path_task_manager = manager
            self.path_task_executor = manager.executor

    def get_snapshot(self) -> SimulationSnapshot:
        with self.lock:
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
                path_task=(
                    self.path_task_manager.snapshot_summary()
                    if self.path_task_manager is not None
                    else None
                ),
            )
