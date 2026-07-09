from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.ship_loader import ShipLoader
from app.models.axis import AxisConfig
from app.models.geometry import ShipLoaderGeometry

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_loader.json")


def load_loader_config(path: str | Path = DEFAULT_CONFIG_PATH) -> tuple[str, ShipLoaderGeometry, dict[str, AxisConfig]]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = json.load(file)

    loader_id = raw["loader_id"]
    geometry = ShipLoaderGeometry.model_validate(raw["geometry"])
    axes = {
        axis_id: AxisConfig.model_validate(
            {
                "axis_id": axis_id,
                "axis_type": axis_config["type"],
                "current": axis_config.get("current", 0.0),
                "target": axis_config.get("target", axis_config.get("current", 0.0)),
                "velocity": axis_config.get("velocity", 1.0),
                "enabled": axis_config.get("enabled", True),
                "running": axis_config.get("running", False),
                "min_value": axis_config.get("min_value"),
                "max_value": axis_config.get("max_value"),
                "tolerance": axis_config.get("tolerance", 1e-3),
            }
        )
        for axis_id, axis_config in raw["axes"].items()
    }
    return loader_id, geometry, axes


def create_default_ship_loader() -> ShipLoader:
    loader_id, geometry, axes = load_loader_config()
    return ShipLoader(loader_id=loader_id, geometry=geometry, axis_configs=axes)

