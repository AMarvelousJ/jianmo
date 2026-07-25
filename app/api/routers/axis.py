from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.command_service import MotionCommandService
from app.api.dependencies import get_command_service
from app.api.errors import path_http_exception
from app.core.path_planning.errors import PathPlanningError
from app.models.command import AxisTargetCommand, BeltCommand
from app.models.snapshot import SimulationSnapshot

router = APIRouter(prefix="/api", tags=["commands"])


@router.post("/axis/{axis_id}/target", response_model=SimulationSnapshot)
def set_axis_target(
    axis_id: str,
    command: AxisTargetCommand,
    service: MotionCommandService = Depends(get_command_service),
) -> SimulationSnapshot:
    try:
        return service.set_axis_target(axis_id, command.target, command.velocity)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/axis/{axis_id}/start", response_model=SimulationSnapshot)
def start_axis(
    axis_id: str,
    service: MotionCommandService = Depends(get_command_service),
) -> SimulationSnapshot:
    try:
        return service.start_axis(axis_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/axis/{axis_id}/stop", response_model=SimulationSnapshot)
def stop_axis(
    axis_id: str,
    service: MotionCommandService = Depends(get_command_service),
) -> SimulationSnapshot:
    try:
        return service.stop_axis(axis_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/belt", response_model=SimulationSnapshot)
def set_belt(
    command: BeltCommand,
    service: MotionCommandService = Depends(get_command_service),
) -> SimulationSnapshot:
    try:
        return service.set_belt(command.speed, command.running)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except PathPlanningError as error:
        raise path_http_exception(error) from error
