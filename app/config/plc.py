from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlcSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SL15_PLC_",
        case_sensitive=False,
        extra="ignore",
    )

    enabled: bool = False
    ip: str = "10.60.97.40"
    slot: int = Field(default=0, ge=0, le=16)
    sync_interval_s: float = Field(default=0.1, ge=0.05, le=10.0)
    timeout_s: float = Field(default=2.0, ge=0.1, le=30.0)
    reconnect_interval_s: float = Field(default=2.0, ge=0.1, le=60.0)
    stale_after_s: float = Field(default=0.5, ge=0.1, le=10.0)


def load_plc_settings() -> PlcSettings:
    return PlcSettings()
