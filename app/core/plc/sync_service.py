from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from app.config.plc import PlcSettings
from app.core.plc.mapping import DINT_MAX, PlcTagMapper
from app.core.plc.transport import PlcTransport, PylogixTransport
from app.models.plc import PlcStatus
from app.models.snapshot import SimulationSnapshot

TransportFactory = Callable[[PlcSettings], PlcTransport]

PROBE_TAGS = (
    "SL15_IF_Version",
    "SL15_IF_PLCHeartbeat",
)


class PlcSyncService:
    def __init__(
        self,
        settings: PlcSettings,
        *,
        mapper: PlcTagMapper | None = None,
        transport_factory: TransportFactory = PylogixTransport,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.mapper = mapper or PlcTagMapper()
        self.transport_factory = transport_factory
        self.monotonic = monotonic
        self._condition = threading.Condition()
        self._status_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_snapshot: SimulationSnapshot | None = None
        self._latest_sim_running = False
        self._latest_publish_monotonic = 0.0
        self._heartbeat = 0
        self._last_heartbeat_monotonic = 0.0
        self._connected = False
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._last_snapshot_sim_time: float | None = None
        self._last_attempt_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_code = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.settings.enabled:
            return
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="sl15-plc-sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def publish_snapshot(
        self,
        snapshot: SimulationSnapshot,
        *,
        sim_running: bool,
    ) -> None:
        if not self.settings.enabled:
            return
        with self._condition:
            self._latest_snapshot = snapshot
            self._latest_sim_running = sim_running
            self._latest_publish_monotonic = self.monotonic()
            self._condition.notify_all()
        with self._status_lock:
            self._last_snapshot_sim_time = snapshot.sim_time

    def status(self) -> PlcStatus:
        thread = self._thread
        with self._status_lock:
            return PlcStatus(
                enabled=self.settings.enabled,
                worker_running=bool(thread and thread.is_alive()),
                connected=self._connected,
                plc_ip=self.settings.ip,
                slot=self.settings.slot,
                sync_interval_ms=round(self.settings.sync_interval_s * 1000),
                successful_cycles=self._successful_cycles,
                failed_cycles=self._failed_cycles,
                heartbeat=self._heartbeat,
                last_snapshot_sim_time=self._last_snapshot_sim_time,
                last_attempt_at=self._last_attempt_at,
                last_success_at=self._last_success_at,
                last_error_code=self._last_error_code,
                last_error=self._last_error,
            )

    def _run(self) -> None:
        transport: PlcTransport | None = None
        next_attempt_monotonic = 0.0
        try:
            while not self._stop_event.is_set():
                snapshot_data = self._wait_for_snapshot()
                if snapshot_data is None:
                    continue
                snapshot, requested_sim_running, published_at = snapshot_data
                now = self.monotonic()
                if now < next_attempt_monotonic:
                    self._stop_event.wait(
                        min(
                            self.settings.sync_interval_s,
                            next_attempt_monotonic - now,
                        )
                    )
                    continue

                if now - self._last_heartbeat_monotonic >= 1.0:
                    self._heartbeat = (self._heartbeat + 1) % (DINT_MAX + 1)
                    self._last_heartbeat_monotonic = now

                sim_running = (
                    requested_sim_running
                    and now - published_at <= self.settings.stale_after_s
                )
                self._record_attempt()
                try:
                    if transport is None:
                        transport = self.transport_factory(self.settings)
                        transport.open()
                        self._verify_target(transport)
                    writes = self.mapper.build_writes(
                        snapshot,
                        heartbeat=self._heartbeat,
                        app_connected=True,
                        sim_running=sim_running,
                        last_error_code=0,
                    )
                    results = transport.write(writes)
                    failures = [result for result in results if not result.success]
                    if failures:
                        details = "; ".join(
                            f"{result.tag_name}: {result.status}"
                            for result in failures[:5]
                        )
                        raise RuntimeError(f"PLC rejected tag writes: {details}")
                    self._record_success()
                    next_attempt_monotonic = now + self.settings.sync_interval_s
                except Exception as error:
                    self._record_failure(error)
                    if transport is not None:
                        transport.close()
                        transport = None
                    next_attempt_monotonic = now + self.settings.reconnect_interval_s
        finally:
            if transport is not None:
                self._write_disconnected_state(transport)
                transport.close()
            with self._status_lock:
                self._connected = False

    def _wait_for_snapshot(
        self,
    ) -> tuple[SimulationSnapshot, bool, float] | None:
        with self._condition:
            if self._latest_snapshot is None and not self._stop_event.is_set():
                self._condition.wait(timeout=self.settings.sync_interval_s)
            if self._stop_event.is_set() or self._latest_snapshot is None:
                return None
            return (
                self._latest_snapshot,
                self._latest_sim_running,
                self._latest_publish_monotonic,
            )

    @staticmethod
    def _verify_target(transport: PlcTransport) -> None:
        results = transport.probe(PROBE_TAGS)
        failures = [result for result in results if not result.success]
        if failures:
            details = "; ".join(
                f"{result.tag_name}: {result.status}" for result in failures
            )
            raise RuntimeError(
                "PLC target verification failed; required SL15 marker tags "
                f"could not be read: {details}"
            )

    @staticmethod
    def _write_disconnected_state(transport: PlcTransport) -> None:
        try:
            transport.write(
                [
                    ("SL15_HIL_AppConnected", False),
                    ("SL15_HIL_SimRunning", False),
                ]
            )
        except Exception:
            pass

    def _record_attempt(self) -> None:
        with self._status_lock:
            self._last_attempt_at = datetime.now(UTC)

    def _record_success(self) -> None:
        with self._status_lock:
            self._connected = True
            self._successful_cycles += 1
            self._last_success_at = datetime.now(UTC)
            self._last_error_code = 0
            self._last_error = None

    def _record_failure(self, error: Exception) -> None:
        with self._status_lock:
            self._connected = False
            self._failed_cycles += 1
            self._last_error_code = 2
            self._last_error = str(error)
