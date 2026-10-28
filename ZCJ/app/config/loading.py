from __future__ import annotations

import json
from pathlib import Path

from app.models.loading import LoadingPlan

DEFAULT_LOADING_PLAN_PATH = Path(__file__).with_name("default_loading_plan.json")


def load_loading_plan(path: str | Path | None = None) -> LoadingPlan:
    source = Path(path) if path is not None else DEFAULT_LOADING_PLAN_PATH
    with source.open("r", encoding="utf-8") as handle:
        return LoadingPlan.model_validate(json.load(handle))
