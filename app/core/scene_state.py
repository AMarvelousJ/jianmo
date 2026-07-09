from __future__ import annotations

from app.models.scene import SceneConfig


class SceneState:
    def __init__(self, scene: SceneConfig) -> None:
        self._scene = scene

    def get_scene(self) -> SceneConfig:
        return self._scene

    def update_scene(self, scene: SceneConfig) -> SceneConfig:
        self._scene = scene
        return self._scene

