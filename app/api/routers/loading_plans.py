from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_loading_task_manager
from app.core.loading.task_manager import LoadingTaskManager
from app.models.loading import LoadingPlanEnvelope, LoadingPlanValidation

router = APIRouter(prefix="/api/loading-plans", tags=["loading-plans"])


@router.get("/current", response_model=LoadingPlanEnvelope)
def get_current_plan(
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingPlanEnvelope:
    return LoadingPlanEnvelope(
        plan=manager.get_plan(),
        validation=manager.validate_plan(
            check_paths=not manager.has_active_task(),
        ),
    )


@router.post("/{plan_id}/validate", response_model=LoadingPlanValidation)
def validate_plan(
    plan_id: str,
    manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> LoadingPlanValidation:
    return manager.validate_plan(plan_id)
