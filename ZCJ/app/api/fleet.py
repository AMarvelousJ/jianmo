"""Seven isolated simulation machines; legacy single-loader API remains compatible."""
from __future__ import annotations

import math
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.api import dependencies as deps
from app.api.state_service import SimulationStateService
from app.api.routers import loading_plans, loading_tasks
from app.config.loader import create_ship_loader, load_loader_profile
from app.config.loading import load_loading_plan
from app.config.scene import load_scene_config
from app.core.loading.plan_validator import LoadingPlanValidator
from app.core.loading.task_manager import LoadingTaskManager
from app.core.path_planning.grid_transformer import GridTransformer
from app.core.path_planning.target_solver import TargetSolver
from app.core.path_planning.path_planner import PathPlanner
from app.core.path_planning.plan_store import PathPlanStore
from app.core.path_planning.task_manager import PathTaskManager
from app.core.scene_state import SceneState
from app.core.simulation_world import SimulationWorld
from app.core.simulation_clock import SimulationClock
from app.models.scene import SceneConfig
from app.models.geometry import ShipLoaderGeometry


class FleetConfiguration(SceneConfig):
    geometry: ShipLoaderGeometry
    travel_min: float = Field(ge=-100, le=0)
    travel_max: float = Field(ge=0, le=100)


class JogRequest(BaseModel):
    session: str
    sequence: int = Field(ge=0)
    axes: dict[str, float]


class SideRequest(BaseModel):
    vessel_id: str


class StopRequest(BaseModel):
    session: str


class FleetMachine:
    def __init__(self, number: int):
        self.number = number
        self.profile = load_loader_profile()
        self.profile.loader_id = f"SL15-{number:02}"
        self.world = SimulationWorld(create_ship_loader(self.profile))
        self.scene = SceneState(load_scene_config())
        self.planner = PathPlanner(self.world, self.scene, GridTransformer(), TargetSolver(self.world.loader.solver))
        self.store = PathPlanStore()
        self.paths = PathTaskManager(self.world, self.scene, self.store, self.planner)
        self.world.attach_path_task_manager(self.paths)
        self.manager = LoadingTaskManager(self.world, self.scene, load_loading_plan(),
            LoadingPlanValidator(self.scene, self.planner), self.planner, self.store, self.paths)
        self.world.attach_loading_task_manager(self.manager)
        # This proxy adds a manual-input timeout without changing the legacy world.
        self.clock = SimulationClock(self, step_s=.05)
        self.session: str | None = None
        self.sequence = -1
        self.deadline = 0.0
        self.configured = False
        self.selected_vessel: str | None = None
        self.defaults = {key: axis.velocity for key, axis in self.world.loader.axes.items()}

    @property
    def paused(self):
        return self.world.paused

    def step(self, dt):
        with self.world.lock:
            if self.session and time.monotonic() > self.deadline:
                self.stop_axes()
            return self.world.step(dt)

    def stop_axes(self):
        self.world.loader.set_belt(0, False)
        for axis in self.world.loader.axes.values():
            axis.reset(axis.current)

    def exit_manual(self):
        with self.world.lock:
            if self.session:
                self.stop_axes()
            self.session = None
            for key, axis in self.world.loader.axes.items():
                axis.velocity = self.defaults[key]

    def configure(self, scene: FleetConfiguration):
        with self.world.lock:
            if len(scene.vessels) != (2 if self.number <= 3 else 1):
                raise HTTPException(422, "设备泊位船舶数量不匹配")
            plain = SceneConfig(revision=scene.revision, vessels=scene.vessels)
            payload = plain.model_dump(exclude={"revision"})
            current = self.scene.get_scene().model_dump(exclude={"revision"})
            same_geometry = self.world.loader.geometry == scene.geometry
            travel = self.world.loader.axes["travel"]
            same_limits = (travel.min_value, travel.max_value) == (scene.travel_min, scene.travel_max)
            if self.configured and payload == current and same_geometry and same_limits:
                return self.scene.get_scene()
            if self.manager.has_active_task() or self.session:
                raise HTTPException(409, "设备作业中，不能更换场景配置")
            self.scene.update_scene(plain)
            self.world.loader.geometry = scene.geometry
            self.profile.geometry = scene.geometry
            travel = self.world.loader.axes["travel"]
            travel.min_value, travel.max_value = scene.travel_min, scene.travel_max
            self.configured = True
            self.selected_vessel = None
            # The lower pair serves the negative lateral side; start its booms
            # facing that vessel instead of snapping across the pier on connect.
            self.world.loader.reset_axes({"travel": 0, "slew": 180 if self.number >= 6 else 0,
                "boom_luff": 10, "boom_extension": 0, "chute_rotate": 0})
            if self.number > 3:
                self.select_side(scene.vessels[0].id)
            return self.scene.get_scene()

    def select_side(self, vessel_id):
        with self.world.lock:
            task = self.manager.get_current()
            if task is not None:
                raise HTTPException(409, "请完成或终止并重置当前任务后再切换船舶")
            vessel = next((v for v in self.scene.get_scene().vessels if v.id == vessel_id), None)
            if not self.configured or vessel is None or not vessel.holds:
                raise HTTPException(422, "请先配置该设备的实际泊位")
            plan = load_loading_plan()
            plan.plan_id = f"fleet-{self.number:02}-{vessel_id}"
            plan.name = f"{self.number:02}号装船机演示配载计划"
            plan.vessel_id = vessel_id
            plan.vessel_name = vessel_id
            mapping = {f"No.{i+1}": h.id for i, h in enumerate(vessel.holds)}
            # Four-hold vessels retain the same 12-batch demonstration total;
            # the fifth hold's batches are assigned to the fourth physical hold.
            for batch in plan.batches():
                index = min(int(batch.hold_no.split('.')[-1]), len(vessel.holds))
                batch.hold_no = f"No.{index}"
                batch.hold_id = mapping[batch.hold_no]
            plan.hold_mapping = mapping
            plan.hold_capacity_m3 = {}
            self.manager.plan = plan
            self.manager.validator = LoadingPlanValidator(self.scene, self.planner, mapping)
            self.selected_vessel = vessel_id
            return {"vessel_id": vessel_id}

    def enter_manual(self):
        with self.world.lock:
            task = self.manager.get_current()
            if task and task.status in self.manager.ACTIVE_STATUSES:
                self.manager.pause_task(task.task_id, reason="manual_control")
                # Discard the child path before any manual motion; preserve cargo,
                # batch index, completed batches and drainage wait.
                internal = self.manager._require_current_locked(task.task_id)
                self.manager._cancel_child_path_locked(internal, "manual_replan")
                internal.current_path_task_id = None
                internal.current_target_world_point = None
                if internal.paused_from_status in {"loading", "positioning"}:
                    internal.paused_from_status = "positioning"
                    self.manager._current_batch_progress_locked(internal).status = "positioning"
            self.stop_axes()
            self.session = uuid4().hex
            self.sequence = -1
            self.deadline = time.monotonic() + .4
            self.world.resume()  # paused loading executor skips cargo; axes can move.
            return {"session": self.session}

    def jog(self, request: JogRequest):
        with self.world.lock:
            if not self.session or request.session != self.session:
                raise HTTPException(409, "手动控制会话已结束")
            if request.sequence <= self.sequence:
                return self.world.get_snapshot()
            if set(request.axes) != set(self.world.loader.axes):
                raise HTTPException(422, "每帧必须提供完整五轴输入")
            if any(not math.isfinite(v) or abs(v) > 1 for v in request.axes.values()):
                raise HTTPException(422, "五轴输入必须是 -1 到 1 的有限数值")
            task = self.manager.get_current()
            if task and task.status in self.manager.ACTIVE_STATUSES and task.status != "paused":
                raise HTTPException(409, "自动任务尚未暂停")
            self.sequence = request.sequence
            self.deadline = time.monotonic() + .4
            for key, value in request.axes.items():
                axis = self.world.loader.axes[key]
                if abs(value) < .001:
                    axis.reset(axis.current)
                else:
                    axis.set_target(axis.max_value if value > 0 else axis.min_value,
                        min(axis.max_velocity, self.defaults[key]) * abs(value))
            return self.world.get_snapshot()


machines = [FleetMachine(i) for i in range(1, 8)]


def mount_fleet(app: FastAPI):
    for machine in machines:
        app.mount(f"/api/fleet/{machine.number:02}", make_app(machine, app))


def make_app(machine: FleetMachine, parent: FastAPI):
    child = FastAPI(exception_handlers=parent.exception_handlers)
    overrides = {
        deps.get_world: machine.world, deps.get_simulation_clock: machine.clock,
        deps.get_loading_task_manager: machine.manager, deps.get_scene_state: machine.scene,
        deps.get_state_service: SimulationStateService(machine.world),
    }
    for dependency, value in overrides.items():
        child.dependency_overrides[dependency] = (lambda item: lambda: item)(value)
    # Read/state/task and clock endpoints reuse the existing contracts. Generic
    # axis/reset/PLC endpoints are deliberately not exposed on fleet machines.
    @child.get("/api/state")
    def snapshot():
        with machine.world.lock:
            value = machine.world.get_snapshot().model_dump(mode="json")
            value["fleet_configured"] = machine.configured
            value["selected_vessel"] = machine.selected_vessel
            return value
    child.include_router(loading_plans.router)
    @child.put("/api/simulation/clock/clients/{client_id}")
    def register_clock(client_id: str):
        return machine.clock.register(client_id)

    @child.delete("/api/simulation/clock/clients/{client_id}")
    def release_clock(client_id: str):
        return machine.clock.release(client_id)

    @child.get("/api/simulation/clock")
    def clock_status():
        return machine.clock.status()

    @child.middleware("http")
    async def guard(request, call_next):
        from fastapi.responses import JSONResponse
        path = request.url.path
        if request.method == "POST" and (path.endswith("/api/loading-tasks") or path.endswith("/resume")):
            if not machine.configured or machine.selected_vessel is None:
                return JSONResponse(status_code=409, content={"detail": "请先选择作业船舶"})
            machine.exit_manual()
        return await call_next(request)

    child.include_router(loading_tasks.router)

    @child.get("/health")
    def health():
        return {"status": "ok"}

    @child.get("/api/scene")
    def scene():
        return machine.scene.get_scene()

    @child.put("/api/fleet-configuration")
    def configure(scene: FleetConfiguration):
        return machine.configure(scene)

    @child.get("/api/selection")
    def selection():
        return {"vessel_id": machine.selected_vessel}

    @child.post("/api/selection")
    def select(request: SideRequest):
        return machine.select_side(request.vessel_id)

    @child.post("/api/manual/enter")
    def enter():
        return machine.enter_manual()

    @child.post("/api/manual/stop")
    def stop(request: StopRequest):
        with machine.world.lock:
            if machine.session == request.session:
                machine.exit_manual()
        return {"stopped": True}

    @child.post("/api/manual/jog")
    def jog(request: JogRequest):
        return machine.jog(request)

    return child
