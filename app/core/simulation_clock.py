from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.simulation_world import SimulationWorld


@dataclass(frozen=True)
class SimulationClockStatus:
    step_s: float
    active_clients: int
    running: bool
    sim_paused: bool


class SimulationClock:
    """Advance the simulation while at least one display client is alive."""

    def __init__(
        self,
        world: SimulationWorld,
        step_s: float = 0.1,
        client_timeout_s: float = 3.0,
    ) -> None:
        self.world = world
        self.step_s = step_s
        self.client_timeout_s = client_timeout_s
        self._clients: dict[str, float] = {}
        self._condition = threading.Condition()
        self._stop_requested = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_requested = False
            self._thread = threading.Thread(
                target=self._run,
                name="shiploader-simulation-clock",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._condition:
            self._stop_requested = True
            self._clients.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.step_s * 3))
        with self._condition:
            self._thread = None

    def register(self, client_id: str) -> SimulationClockStatus:
        self.start()
        with self._condition:
            self._expire_clients_locked()
            self._clients[client_id] = time.monotonic() + self.client_timeout_s
            self._condition.notify_all()
            return self._status_locked()

    def release(self, client_id: str) -> SimulationClockStatus:
        with self._condition:
            self._clients.pop(client_id, None)
            self._expire_clients_locked()
            self._condition.notify_all()
            return self._status_locked()

    def status(self) -> SimulationClockStatus:
        with self._condition:
            self._expire_clients_locked()
            return self._status_locked()

    @property
    def has_active_clients(self) -> bool:
        return self.status().active_clients > 0

    def _run(self) -> None:
        next_step = time.monotonic() + self.step_s
        while True:
            with self._condition:
                self._expire_clients_locked()
                while not self._stop_requested and not self._clients:
                    self._condition.wait(timeout=self.client_timeout_s)
                    self._expire_clients_locked()
                    next_step = time.monotonic() + self.step_s
                if self._stop_requested:
                    return
                delay = next_step - time.monotonic()
                if delay > 0:
                    self._condition.wait(timeout=delay)
                    continue
            self.world.step(self.step_s)
            next_step += self.step_s
            if next_step < time.monotonic() - self.step_s:
                next_step = time.monotonic() + self.step_s

    def _expire_clients_locked(self) -> None:
        now = time.monotonic()
        for client_id, deadline in tuple(self._clients.items()):
            if deadline <= now:
                self._clients.pop(client_id, None)

    def _status_locked(self) -> SimulationClockStatus:
        return SimulationClockStatus(
            step_s=self.step_s,
            active_clients=len(self._clients),
            running=bool(self._clients),
            sim_paused=self.world.paused,
        )
