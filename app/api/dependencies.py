from __future__ import annotations

from app.api.command_service import MotionCommandService
from app.api.state_service import SimulationStateService
from app.config.loader import create_ship_loader, load_loader_profile
from app.config.scene import load_scene_config
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld

_loader_profile = load_loader_profile()
_world = SimulationWorld(create_ship_loader(_loader_profile))
_scene_state = SceneState(load_scene_config())


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
