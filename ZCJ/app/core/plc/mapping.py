from __future__ import annotations

from app.models.snapshot import SimulationSnapshot

AXIS_ORDER = (
    "travel",
    "slew",
    "boom_luff",
    "boom_extension",
    "chute_rotate",
)

DINT_MAX = 2_147_483_647


class PlcTagMapper:
    def build_writes(
        self,
        snapshot: SimulationSnapshot,
        *,
        heartbeat: int,
        app_connected: bool,
        sim_running: bool,
        ack_seq: int = 0,
        ack_code: int = 0,
        last_error_code: int = 0,
    ) -> list[tuple[str, object]]:
        axis_states = [snapshot.axis_states[axis_id] for axis_id in AXIS_ORDER]
        running_mask = self._mask([state.running for state in axis_states])
        at_target_mask = self._mask([state.at_target for state in axis_states])
        fault_flags = [
            bool(state.constraint_result.get("faulted", False))
            for state in axis_states
        ]
        fault_mask = self._mask(fault_flags)
        fault_codes = [
            int(state.constraint_result.get("fault_code", 0))
            for state in axis_states
        ]
        sim_time_ms = int(round(snapshot.sim_time * 1000.0)) % (DINT_MAX + 1)

        writes: list[tuple[str, object]] = [
            ("SL15_HIL_AppHeartbeat", int(heartbeat) % (DINT_MAX + 1)),
            ("SL15_HIL_AckSeq", int(ack_seq)),
            ("SL15_HIL_AckCode", int(ack_code)),
            ("SL15_HIL_AppConnected", bool(app_connected)),
            ("SL15_HIL_SimRunning", bool(sim_running)),
            ("SL15_HIL_SimTime_ms", sim_time_ms),
            ("SL15_HIL_AxisRunningMask", running_mask),
            ("SL15_HIL_AxisAtTargetMask", at_target_mask),
            ("SL15_HIL_AxisFaultMask", fault_mask),
            ("SL15_HIL_BeltRunning", bool(snapshot.belt_state.running)),
            ("SL15_HIL_BeltSpeed_mps", float(snapshot.belt_state.speed_mps)),
            ("SL15_HIL_LastErrorCode", int(last_error_code)),
        ]
        writes.extend(
            (f"SL15_HIL_AxisActual[{index}]", float(state.current))
            for index, state in enumerate(axis_states)
        )
        writes.extend(
            (f"SL15_HIL_AxisFaultCode[{index}]", fault_codes[index])
            for index in range(len(axis_states))
        )
        return writes

    @staticmethod
    def _mask(flags: list[bool]) -> int:
        mask = 0
        for index, flag in enumerate(flags):
            if flag:
                mask |= 1 << index
        return mask
