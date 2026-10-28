from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.config.plc import PlcSettings


@dataclass(frozen=True)
class PlcWriteResult:
    tag_name: str
    success: bool
    status: str


class PlcTransport(Protocol):
    def open(self) -> None: ...

    def probe(self, tag_names: Sequence[str]) -> list[PlcWriteResult]: ...

    def write(self, values: Sequence[tuple[str, object]]) -> list[PlcWriteResult]: ...

    def close(self) -> None: ...


class PylogixTransport:
    def __init__(self, settings: PlcSettings) -> None:
        self.settings = settings
        self._plc = None

    def open(self) -> None:
        if self._plc is not None:
            return
        try:
            from pylogix import PLC
        except ImportError as error:
            raise RuntimeError(
                "pylogix is not installed; install project dependencies before enabling PLC sync"
            ) from error
        self._plc = PLC(
            self.settings.ip,
            slot=self.settings.slot,
            timeout=self.settings.timeout_s,
        )

    def probe(self, tag_names: Sequence[str]) -> list[PlcWriteResult]:
        plc = self._require_plc()
        responses = plc.Read(list(tag_names))
        return self._normalize_responses(responses)

    def write(self, values: Sequence[tuple[str, object]]) -> list[PlcWriteResult]:
        plc = self._require_plc()
        responses = plc.Write(list(values))
        return self._normalize_responses(responses)

    def close(self) -> None:
        if self._plc is None:
            return
        try:
            self._plc.Close()
        finally:
            self._plc = None

    def _require_plc(self):
        if self._plc is None:
            raise RuntimeError("PLC transport is not open")
        return self._plc

    @staticmethod
    def _normalize_responses(responses) -> list[PlcWriteResult]:
        if not isinstance(responses, list):
            responses = [responses]
        return [
            PlcWriteResult(
                tag_name=str(response.TagName),
                success=str(response.Status) == "Success",
                status=str(response.Status),
            )
            for response in responses
        ]
