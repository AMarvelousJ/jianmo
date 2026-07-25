from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.ship_loader import ShipLoader
from app.models.axis import AxisConfig
from app.models.geometry import ShipLoaderGeometry
from app.models.loader_config import LoaderProfile

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_loader.json")


def load_loader_profile(path: str | Path = DEFAULT_CONFIG_PATH) -> LoaderProfile:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw: dict[str, Any] = json.load(file)

    raw["axes"] = {
        axis_id: {
            "axis_id": axis_id,
            "axis_type": axis_config["type"],
            "current": axis_config.get("current", 0.0),
            "target": axis_config.get("target", axis_config.get("current", 0.0)),
            "velocity": axis_config.get("velocity", 1.0),
            "max_velocity": axis_config.get("max_velocity", axis_config.get("velocity", 1.0)),
            "enabled": axis_config.get("enabled", True),
            "running": axis_config.get("running", False),
            "min_value": axis_config.get("min_value"),
            "max_value": axis_config.get("max_value"),
            "tolerance": axis_config.get("tolerance", 1e-3),
        }
        for axis_id, axis_config in raw["axes"].items()
    }
    return LoaderProfile.model_validate(raw)


def load_loader_config(path: str | Path = DEFAULT_CONFIG_PATH) -> tuple[str, ShipLoaderGeometry, dict[str, AxisConfig]]:
    profile = load_loader_profile(path)
    return profile.loader_id, profile.geometry, profile.axes


def create_ship_loader(profile: LoaderProfile) -> ShipLoader:
    return ShipLoader(
        loader_id=profile.loader_id,
        geometry=profile.geometry,
        axis_configs=profile.axes,
    )


def create_default_ship_loader() -> ShipLoader:
    return create_ship_loader(load_loader_profile())
