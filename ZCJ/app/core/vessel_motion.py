from __future__ import annotations

import math

from app.models.snapshot import VesselPose


class VesselMotion:
    def __init__(
        self,
        roll_deg: float = 0.0,
        pitch_deg: float = 0.0,
        roll_amplitude_deg: float = 0.0,
        roll_period_s: float = 0.0,
        roll_phase_deg: float = 0.0,
        pitch_amplitude_deg: float = 0.0,
        pitch_period_s: float = 0.0,
        pitch_phase_deg: float = 0.0,
    ) -> None:
        self.roll_deg = roll_deg
        self.pitch_deg = pitch_deg
        self.roll_amplitude_deg = roll_amplitude_deg
        self.roll_period_s = roll_period_s
        self.roll_phase_deg = roll_phase_deg
        self.pitch_amplitude_deg = pitch_amplitude_deg
        self.pitch_period_s = pitch_period_s
        self.pitch_phase_deg = pitch_phase_deg

    def pose_at(self, sim_time: float) -> VesselPose:
        roll = self.roll_deg + self._wave(
            self.roll_amplitude_deg,
            self.roll_period_s,
            self.roll_phase_deg,
            sim_time,
        )
        pitch = self.pitch_deg + self._wave(
            self.pitch_amplitude_deg,
            self.pitch_period_s,
            self.pitch_phase_deg,
            sim_time,
        )
        return VesselPose(
            roll_deg=roll,
            pitch_deg=pitch,
            used_for_discharge_coordinate=False,
        )

    @staticmethod
    def _wave(amplitude: float, period: float, phase_deg: float, sim_time: float) -> float:
        if amplitude == 0 or period <= 0:
            return 0.0
        phase_rad = math.radians(phase_deg)
        return amplitude * math.sin((2.0 * math.pi * sim_time / period) + phase_rad)

