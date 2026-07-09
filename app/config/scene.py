from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.scene import SceneConfig

DEFAULT_SCENE_PATH = Path(__file__).with_name("default_scene.json")


def load_scene_config(path: str | Path = DEFAULT_SCENE_PATH) -> SceneConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = json.load(file)
    return SceneConfig.model_validate(raw)

