from __future__ import annotations

import threading

from app.models.scene import SceneConfig


class SceneState:
    def __init__(self, scene: SceneConfig) -> None:
        self._revision = max(1, scene.revision)
        self._scene = scene.model_copy(update={"revision": self._revision}, deep=True)
        self._lock = threading.RLock()

    def get_scene(self) -> SceneConfig:
        with self._lock:
            return self._scene

    def update_scene(self, scene: SceneConfig) -> SceneConfig:
        with self._lock:
            self._revision += 1
            self._scene = scene.model_copy(update={"revision": self._revision}, deep=True)
            return self._scene
