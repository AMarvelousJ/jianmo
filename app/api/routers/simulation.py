from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.command_service import MotionCommandService
from app.api.dependencies import get_command_service
from app.models.command import StepCommand
from app.models.snapshot import SimulationSnapshot

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.post("/pause", response_model=SimulationSnapshot)
def pause(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    return service.pause_simulation()


@router.post("/resume", response_model=SimulationSnapshot)
def resume(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    return service.resume_simulation()


@router.post("/reset", response_model=SimulationSnapshot)
def reset(service: MotionCommandService = Depends(get_command_service)) -> SimulationSnapshot:
    return service.reset_simulation()


@router.post("/step", response_model=SimulationSnapshot)
def step(
    command: StepCommand,
    service: MotionCommandService = Depends(get_command_service),
) -> SimulationSnapshot:
    return service.step_simulation(command.dt)

