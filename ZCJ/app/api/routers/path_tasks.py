from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_path_task_manager
from app.api.errors import path_http_exception
from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.task_manager import PathTaskManager
from app.models.path_planning import PathTask, PathTaskCreateRequest

router = APIRouter(prefix="/api/path-tasks", tags=["path-tasks"])


@router.post("", response_model=PathTask, status_code=status.HTTP_201_CREATED)
def create_task(
    request: PathTaskCreateRequest,
    response: Response,
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask:
    try:
        task, created = manager.create_task(request.request_id, request.plan_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error
    if not created:
        response.status_code = status.HTTP_200_OK
    return task


@router.get("/current", response_model=PathTask | None)
def get_current_task(
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask | None:
    return manager.get_current()


@router.get("", response_model=list[PathTask])
def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> list[PathTask]:
    return manager.list_tasks(limit)


@router.get("/{task_id}", response_model=PathTask)
def get_task(
    task_id: str,
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask:
    try:
        return manager.get_task(task_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/{task_id}/pause", response_model=PathTask)
def pause_task(
    task_id: str,
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask:
    try:
        return manager.pause_task(task_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/{task_id}/resume", response_model=PathTask)
def resume_task(
    task_id: str,
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask:
    try:
        return manager.resume_task(task_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/{task_id}/cancel", response_model=PathTask)
def cancel_task(
    task_id: str,
    manager: PathTaskManager = Depends(get_path_task_manager),
) -> PathTask:
    try:
        return manager.cancel_task(task_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error
