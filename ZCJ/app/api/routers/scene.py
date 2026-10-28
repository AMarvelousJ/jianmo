from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_scene_state
from app.core.scene_state import SceneState
from app.models.scene import SceneConfig

router = APIRouter(prefix="/api/scene", tags=["scene"])


@router.get("", response_model=SceneConfig)
def get_scene(scene_state: SceneState = Depends(get_scene_state)) -> SceneConfig:
    return scene_state.get_scene()


@router.put("", response_model=SceneConfig)
def update_scene(
    scene: SceneConfig,
    scene_state: SceneState = Depends(get_scene_state),
) -> SceneConfig:
    return scene_state.update_scene(scene)

