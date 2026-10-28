from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PlcStatus(BaseModel):
    enabled: bool
    worker_running: bool
    connected: bool
    plc_ip: str
    slot: int
    sync_interval_ms: int
    successful_cycles: int = 0
    failed_cycles: int = 0
    heartbeat: int = 0
    last_snapshot_sim_time: float | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: int = 0
    last_error: str | None = None
