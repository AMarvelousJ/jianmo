"""Video-preview motion service, without material operations or persistence."""
import copy
import json
from pathlib import Path

from fastapi.responses import JSONResponse

from .api import create_app
from .reclaim_pilot import PreviewWorld


def preview_config():
    config = json.loads((Path(__file__).resolve().parents[1] / "config/machines.json").read_text(encoding="utf-8"))
    config = copy.deepcopy(config)
    config["version"] = "yard-video-preview-v3"
    for machine in config["machines"]:
        if machine["role"] == "Stacking":
            machine["axes"]["slew"].update(minimum=-20.0, maximum=200.0)
        else:
            machine["axes"]["slew"].update(minimum=-80.0, maximum=260.0)
    return config


def create_preview_app(world=None, run_clock=True):
    app = create_app(world or PreviewWorld(config=preview_config(), snapshot_path=None), run_clock=run_clock,
                     clock_step_budget=2)

    @app.middleware("http")
    async def motion_only(request, call_next):
        # Preview coal markers are presentation only; block calls that change coal stock.
        if request.method != "GET":
            if request.url.path.startswith("/api/material"):
                return JSONResponse(status_code=409, content={"detail": {"message": "视频预览仅支持运动和煤流示意"}})
            if request.url.path.endswith("/commands"):
                body = await request.json()
                if body.get("kind") in {"start_job", "pause_job", "resume_job", "terminate_job", "finish_job", "reset_material"}:
                    return JSONResponse(status_code=409, content={"detail": {"message": "视频预览不执行物料作业"}})
        return await call_next(request)

    return app
