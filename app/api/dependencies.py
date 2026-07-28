from __future__ import annotations

import logging

from app.api.command_service import MotionCommandService
from app.api.state_service import SimulationStateService
from app.config.loading import load_loading_plan
from app.config.loader import create_ship_loader, load_loader_profile
from app.config.plc import load_plc_settings
from app.config.scene import load_scene_config
from app.core.plc.sync_service import PlcSyncService
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.core.path_planning.grid_transformer import GridTransformer
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.plan_store import PathPlanStore
from app.core.path_planning.target_solver import TargetSolver
from app.core.path_planning.task_manager import PathTaskManager
from app.core.loading.plan_validator import LoadingPlanValidator
from app.core.loading.errors import LoadingError
from app.core.loading.task_manager import LoadingTaskManager

logger = logging.getLogger(__name__)

_loader_profile = load_loader_profile()
_world = SimulationWorld(create_ship_loader(_loader_profile))
_scene_state = SceneState(load_scene_config())
_grid_transformer = GridTransformer()
_target_solver = TargetSolver(_world.loader.solver)
_path_planner = PathPlanner(
    _world,
    _scene_state,
    _grid_transformer,
    _target_solver,
)
_path_plan_store = PathPlanStore()
_path_task_manager = PathTaskManager(
    _world,
    _scene_state,
    _path_plan_store,
    _path_planner,
)
_world.attach_path_task_manager(_path_task_manager)
_loading_task_manager: LoadingTaskManager | None = None
_loading_plan_error: str | None = None
try:
    _loading_plan = load_loading_plan()
    _loading_plan_validator = LoadingPlanValidator(
        _scene_state,
        _path_planner,
    )
    _loading_task_manager = LoadingTaskManager(
        _world,
        _scene_state,
        _loading_plan,
        _loading_plan_validator,
        _path_planner,
        _path_plan_store,
        _path_task_manager,
    )
    _world.attach_loading_task_manager(_loading_task_manager)
except (OSError, ValueError) as error:
    _loading_plan_error = str(error)
    logger.exception("default loading plan is unavailable")
_plc_sync_service = PlcSyncService(load_plc_settings())
_world.attach_plc_sync_service(_plc_sync_service)


def get_world() -> SimulationWorld:
    return _world


def get_loader_profile():
    return _loader_profile


def get_command_service() -> MotionCommandService:
    return MotionCommandService(_world)


def get_state_service() -> SimulationStateService:
    return SimulationStateService(_world)


def get_scene_state() -> SceneState:
    return _scene_state


def get_grid_transformer() -> GridTransformer:
    return _grid_transformer


def get_path_planner() -> PathPlanner:
    return _path_planner


def get_path_plan_store() -> PathPlanStore:
    return _path_plan_store


def get_path_task_manager() -> PathTaskManager:
    return _path_task_manager


def get_loading_task_manager() -> LoadingTaskManager:
    if _loading_task_manager is None:
        raise LoadingError(
            "LOADING_PLAN_INVALID",
            "默认配载计划加载失败，一键装船功能不可用。",
            status_code=400,
            context={"reason": _loading_plan_error},
        )
    return _loading_task_manager


def get_plc_sync_service() -> PlcSyncService:
    return _plc_sync_service
