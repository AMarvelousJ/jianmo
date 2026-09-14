from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.command_service import MotionCommandService
from app.api.dependencies import get_command_service, get_simulation_clock
from app.api.errors import path_http_exception
from app.core.path_planning.errors import PathPlanningError
from app.core.simulation_clock import SimulationClock, SimulationClockStatus
from app.models.command import StepCommand
from app.models.snapshot import SimulationSnapshot

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


class ClockClientRegistration(BaseModel):
    client_name: str = "display"


@router.put("/clock/clients/{client_id}", response_model=SimulationClockStatus)
def register_clock_client(
    client_id: str,
    _: ClockClientRegistration,
    clock: SimulationClock = Depends(get_simulation_clock),
) -> SimulationClockStatus:
    return clock.register(client_id)


@router.delete("/clock/clients/{client_id}", response_model=SimulationClockStatus)
def release_clock_client(
    client_id: str,
    clock: SimulationClock = Depends(get_simulation_clock),
) -> SimulationClockStatus:
    return clock.release(client_id)


@router.get("/clock", response_model=SimulationClockStatus)
def get_clock_status(
    clock: SimulationClock = Depends(get_simulation_clock),
) -> SimulationClockStatus:
    return clock.status()


@router.post("/pause", response_model=SimulationSnapshot)
def pause(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    try:
        return service.pause_simulation()
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/resume", response_model=SimulationSnapshot)
def resume(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    try:
        return service.resume_simulation()
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/reset", response_model=SimulationSnapshot)
def reset(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    return service.reset_simulation()


@router.post("/step", response_model=SimulationSnapshot)
def step(
    command: StepCommand,
    service: MotionCommandService = Depends(get_command_service),
    clock: SimulationClock = Depends(get_simulation_clock),
) -> SimulationSnapshot:
    # The legacy browser still posts steps. Once Unity owns the shared clock,
    # return the current state so the simulation cannot be advanced twice.
    if clock.has_active_clients:
        return service.world.get_snapshot()
    return service.step_simulation(command.dt)
