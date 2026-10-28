from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_loading_task_manager, get_world
from app.core.loading.task_manager import LoadingTaskManager
from app.core.simulation_world import SimulationWorld
from app.models.loading import (
    LoadingEvent,
    LoadingResetResponse,
    LoadingTask,
    LoadingTaskCreateRequest,
)

router = APIRouter(prefix="/api/loading-tasks", tags=["loading-tasks"])


@router.post("", response_model=LoadingTask, status_code=status.HTTP_201_CREATED)
def create_task(
    request: LoadingTaskCreateRequest,
    response: Response,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask:
    task, created = manager.create_task(request)
    if not created:
        response.status_code = status.HTTP_200_OK
    return task


@router.get("/current", response_model=LoadingTask | None)
def get_current_task(
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask | None:
    return manager.get_current()


@router.get("", response_model=list[LoadingTask])
def list_tasks(
    limit: int = Query(default=50, ge=1, le=50),
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> list[LoadingTask]:
    return manager.list_tasks(limit)


@router.get("/{task_id}", response_model=LoadingTask)
def get_task(
    task_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask:
    return manager.get_task(task_id)


@router.get("/{task_id}/events", response_model=list[LoadingEvent])
def list_events(
    task_id: str,
    event_type: str | None = None,
    round_no: int | None = Query(default=None, ge=1),
    batch_no: int | None = Query(default=None, ge=1),
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> list[LoadingEvent]:
    return manager.list_events(
        task_id,
        event_type=event_type,
        round_no=round_no,
        batch_no=batch_no,
    )


@router.post("/{task_id}/pause", response_model=LoadingTask)
def pause_task(
    task_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask:
    return manager.pause_task(task_id)


@router.post("/{task_id}/resume", response_model=LoadingTask)
def resume_task(
    task_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask:
    return manager.resume_task(task_id)


@router.post("/{task_id}/cancel", response_model=LoadingTask)
def cancel_task(
    task_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingTask:
    return manager.cancel_task(task_id)


@router.post("/{task_id}/reset", response_model=LoadingResetResponse)
def reset_task(
    task_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
    world: SimulationWorld = Depends(get_world),
) -> LoadingResetResponse:
    task = manager.reset_task(task_id)
    return LoadingResetResponse(
        task=task,
        snapshot=world.get_snapshot().model_dump(mode="json"),
    )
