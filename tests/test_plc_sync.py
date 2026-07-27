from __future__ import annotations

import threading
import time

import pytest

from app.config.loader import create_default_ship_loader
from app.config.plc import PlcSettings
from app.core.plc.mapping import PlcTagMapper
from app.core.plc.sync_service import PlcSyncService
from app.core.plc.transport import PlcWriteResult
from app.core.simulation_world import SimulationWorld


class FakeTransport:
    def __init__(self, settings: PlcSettings) -> None:
        self.settings = settings
        self.opened = False
        self.closed = False
        self.probes: list[tuple[str, ...]] = []
        self.writes: list[list[tuple[str, object]]] = []
        self.lock = threading.Lock()

    def open(self) -> None:
        self.opened = True

    def probe(self, tag_names) -> list[PlcWriteResult]:
        self.probes.append(tuple(tag_names))
        return [
            PlcWriteResult(tag_name=name, success=True, status="Success")
            for name in tag_names
        ]

    def write(self, values) -> list[PlcWriteResult]:
        batch = list(values)
        with self.lock:
            self.writes.append(batch)
        return [
            PlcWriteResult(tag_name=name, success=True, status="Success")
            for name, _ in batch
        ]

    def close(self) -> None:
        self.closed = True


def wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true before timeout")


def test_plc_mapper_uses_documented_axis_order_and_masks():
    world = SimulationWorld(create_default_ship_loader())
    world.loader.set_axis_target("travel", 10.0, velocity=0.5)
    world.loader.start_axis("travel")
    snapshot = world.step(1.0)

    writes = dict(
        PlcTagMapper().build_writes(
            snapshot,
            heartbeat=7,
            app_connected=True,
            sim_running=True,
        )
    )

    assert writes["SL15_HIL_AppHeartbeat"] == 7
    assert writes["SL15_HIL_AppConnected"] is True
    assert writes["SL15_HIL_SimRunning"] is True
    assert writes["SL15_HIL_SimTime_ms"] == 1000
    assert writes["SL15_HIL_AxisActual[0]"] == pytest.approx(0.5)
    assert writes["SL15_HIL_AxisActual[1]"] == pytest.approx(0.0)
    assert writes["SL15_HIL_AxisActual[2]"] == pytest.approx(10.0)
    assert writes["SL15_HIL_AxisActual[3]"] == pytest.approx(0.0)
    assert writes["SL15_HIL_AxisActual[4]"] == pytest.approx(0.0)
    assert writes["SL15_HIL_AxisRunningMask"] == 0b00001
    assert writes["SL15_HIL_AxisAtTargetMask"] == 0b11110


def test_plc_sync_service_writes_latest_snapshot_and_disconnects_cleanly():
    settings = PlcSettings(
        enabled=True,
        ip="127.0.0.1",
        sync_interval_s=0.05,
        reconnect_interval_s=0.1,
        stale_after_s=0.2,
    )
    transports: list[FakeTransport] = []

    def transport_factory(current_settings: PlcSettings) -> FakeTransport:
        transport = FakeTransport(current_settings)
        transports.append(transport)
        return transport

    service = PlcSyncService(
        settings,
        transport_factory=transport_factory,
    )
    world = SimulationWorld(create_default_ship_loader())
    service.publish_snapshot(world.get_snapshot(), sim_running=True)

    service.start()
    wait_until(lambda: service.status().successful_cycles >= 1)
    active_status = service.status()
    service.stop()

    assert active_status.connected is True
    assert active_status.last_error is None
    assert len(transports) == 1
    transport = transports[0]
    assert transport.opened is True
    assert transport.probes == [
        ("SL15_IF_Version", "SL15_IF_PLCHeartbeat")
    ]
    first_batch = dict(transport.writes[0])
    assert first_batch["SL15_HIL_AppConnected"] is True
    assert "SL15_HIL_AxisActual[4]" in first_batch
    assert transport.writes[-1] == [
        ("SL15_HIL_AppConnected", False),
        ("SL15_HIL_SimRunning", False),
    ]
    assert transport.closed is True
    assert service.status().connected is False
