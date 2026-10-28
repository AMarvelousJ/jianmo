"""Video-preview motion service, without material operations or persistence."""
import copy
import json
import math
from pathlib import Path

from fastapi.responses import JSONResponse

from .api import create_app
from .reclaim_pilot import PreviewWorld

REAL_SCALE = 55.0 / 33.0
REAL_ROW_PITCH = 60.0
OLD_ROW_PITCH = 36.0
OLD_FIRST_TRACK_Z = -192.0
REAL_FIRST_TRACK_Z = -180.0
RECLAIMER_REST_OFFSET_DEG = 35.0


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


def real_scale_preview_config():
    """Independent 1 m/unit scene config; the legacy 8001 and v3 scenes stay intact."""
    config = preview_config()
    config['version'] = 'yard-real-scale-preview-v1'
    for machine in config['machines']:
        scene = machine['scene']
        track = round((OLD_FIRST_TRACK_Z - scene['z']) / OLD_ROW_PITCH)
        if abs(OLD_FIRST_TRACK_Z - track * OLD_ROW_PITCH - scene['z']) > 1e-6:
            raise ValueError(f"Unknown stockyard track for {machine['machine_id']}")
        scene['z'] = REAL_FIRST_TRACK_Z - track * REAL_ROW_PITCH
        scene['scale'] = REAL_SCALE
        if machine['role'] == 'Reclaiming':
            # Park the two machines on a shared track towards their respective coal segments.
            scene['rest_slew_offset'] = (RECLAIMER_REST_OFFSET_DEG if scene['x'] < -320
                                         else -RECLAIMER_REST_OFFSET_DEG)
            machine['axes']['luff'].update(minimum=-15.0, maximum=16.0)
    return config


def real_scale_geometry_config():
    config_dir = Path(__file__).resolve().parents[1] / 'config'
    path = config_dir / 'geometry.json'
    geometry = json.loads(path.read_text(encoding='utf-8'))
    wheel = json.loads((config_dir / 'rc01-preview-geometry.json').read_text(encoding='utf-8'))
    wheel_scale = REAL_SCALE * wheel['wheel_scale'][0]
    cutters = wheel['teeth'] + wheel['scoops']
    cut_radius = max(math.hypot(*box['center'][:2]) +
                     sum(math.hypot(*axis[:2]) for axis in box['axes']) for box in cutters)
    axial_min = min([wheel['body_axial_min_wheel_local']] + [
        box['center'][2] - sum(abs(axis[2]) for axis in box['axes']) for box in cutters])
    axial_max = max([wheel['body_axial_max_wheel_local']] + [
        box['center'][2] + sum(abs(axis[2]) for axis in box['axes']) for box in cutters])
    geometry['version'] = 'yard-real-scale-video-geometry-v1'
    geometry['source'] = 'VideoReclaimer preview rig: 33 m model boom at 55/33 scene scale'
    geometry['kinematics'].update(scale=REAL_SCALE, pivot_height=12.55,
                                  yaw_offset_deg=-90.0,
                                  wheel_center_boom_local=[33.0, .35],
                                  outlet_boom_local=[33.0, .35])
    geometry['wheel'].update(swept_radius=cut_radius * wheel_scale,
                             axial_min=axial_min * wheel_scale,
                             axial_max=axial_max * wheel_scale)
    return geometry


def create_real_scale_preview_app(world=None, run_clock=True):
    return create_preview_app(world=world or PreviewWorld(
        config=real_scale_preview_config(), geometry_config=real_scale_geometry_config(),
        pilot_root_scale=REAL_SCALE, snapshot_path=None), run_clock=run_clock)


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
