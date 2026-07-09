from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_state_service
from app.api.state_service import SimulationStateService
from app.models.axis import AxisState
from app.models.pose import Vec3
from app.models.snapshot import SimulationSnapshot

router = APIRouter(prefix="/api/state", tags=["state"])


@router.get("", response_model=SimulationSnapshot)
def get_state(service: SimulationStateService = Depends(get_state_service)) -> SimulationSnapshot:
    return service.get_snapshot()


@router.get("/axis", response_model=dict[str, AxisState])
def get_axis_states(service: SimulationStateService = Depends(get_state_service)) -> dict[str, AxisState]:
    return service.get_axis_states()


@router.get("/key-points", response_model=dict[str, Vec3])
def get_key_points(service: SimulationStateService = Depends(get_state_service)) -> dict[str, Vec3]:
    return service.get_key_points()

