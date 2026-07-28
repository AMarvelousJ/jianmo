from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_grid_transformer,
    get_loading_task_manager,
    get_path_plan_store,
    get_path_planner,
    get_scene_state,
)
from app.api.errors import path_http_exception
from app.core.loading.task_manager import LoadingTaskManager
from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.grid_transformer import GridTransformer
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.plan_store import PathPlanStore
from app.core.scene_state import SceneState
from app.models.path_planning import (
    GridTargetRequest,
    HoldGridResponse,
    PathPlan,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["path-plans"])


@router.get(
    "/api/vessels/{vessel_id}/holds/{hold_id}/grid",
    response_model=HoldGridResponse,
)
def get_hold_grid(
    vessel_id: str,
    hold_id: str,
    scene_state: SceneState = Depends(get_scene_state),
    transformer: GridTransformer = Depends(get_grid_transformer),
) -> HoldGridResponse:
    try:
        return transformer.grid_response(scene_state.get_scene(), vessel_id, hold_id)
    except PathPlanningError as error:
        raise path_http_exception(error) from error


@router.post("/api/path-plans/preview", response_model=PathPlan)
def preview_path(
    request: GridTargetRequest,
    planner: PathPlanner = Depends(get_path_planner),
    store: PathPlanStore = Depends(get_path_plan_store),
    loading_manager: LoadingTaskManager = Depends(get_loading_task_manager),
) -> PathPlan:
    logger.info(
        json.dumps(
            {
                "event": "path_preview_requested",
                **request.model_dump(),
            },
            ensure_ascii=False,
        )
    )
    try:
        loading_manager.ensure_standalone_path_allowed()
        plan = store.put(planner.preview(request))
    except PathPlanningError as error:
        logger.info(
            json.dumps(
                {
                    "event": "path_preview_failed",
                    "error_code": error.code,
                    **request.model_dump(),
                },
                ensure_ascii=False,
            )
        )
        raise path_http_exception(error) from error
    logger.info(
        json.dumps(
            {
                "event": "path_preview_succeeded",
                "plan_id": plan.plan_id,
                "scene_revision": plan.scene_revision,
                "vessel_id": plan.target.vessel_id,
                "hold_id": plan.target.hold_id,
                "column": plan.target.column,
                "row": plan.target.row,
            },
            ensure_ascii=False,
        )
    )
    return plan
