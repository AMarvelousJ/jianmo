import asyncio
import contextlib
import time
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .world import MotionError, World


class ClientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=128)


class ControlRequest(ClientRequest):
    token: str = Field(min_length=1, max_length=128)
    generation: StrictInt


class CommandRequest(ControlRequest):
    command_id: str = Field(min_length=1, max_length=128)
    command_seq: StrictInt
    kind: str
    payload: dict = Field(default_factory=dict)


class OtherMachineControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str
    token: str = Field(min_length=1, max_length=128)
    generation: StrictInt


class MaterialSceneRequest(ControlRequest):
    machine_id: str
    command_id: str = Field(min_length=1, max_length=128)
    command_seq: StrictInt
    mode: str
    confirm: StrictBool = False
    controls: list[OtherMachineControl] = Field(default_factory=list)


def create_app(world=None, run_clock=True):
    world = world or World(snapshot_path=os.environ.get("DQLJ_SNAPSHOT_PATH") or
                           Path(__file__).resolve().parents[1] / "data/material-snapshot.json")

    async def clock_loop():
        last = time.monotonic()
        accumulator = 0.0
        step = world.config["step"]
        while True:
            await asyncio.sleep(step)
            now = time.monotonic()
            accumulator += now - last
            last = now
            # Expiry uses wall clock even if a temporarily stalled service catches up.
            while accumulator >= step:
                world.advance(step)
                accumulator -= step
                if accumulator > 1:
                    await asyncio.sleep(0)

    @asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(clock_loop()) if run_clock else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            world.save_snapshot()

    app = FastAPI(title="Yard Machine Motion Simulation", lifespan=lifespan)
    app.state.world = world

    @app.exception_handler(MotionError)
    async def error_handler(_, error):
        return JSONResponse(status_code=error.status, content={"detail": dict(code=error.code, message=error.message, context={})})

    @app.get("/health")
    def health():
        return dict(status="ok", server_instance_id=world.instance)

    @app.get("/api/machines")
    def machines():
        return dict(config_version=world.config["version"], demo=world.config["demo"], machines=world.config["machines"])

    @app.get("/api/state")
    def state():
        return world.state()

    @app.post("/api/machines/{machine_id}/control/acquire")
    def acquire(machine_id: str, body: ClientRequest):
        return world.acquire(machine_id, body.client_id)

    @app.put("/api/machines/{machine_id}/control/heartbeat")
    def heartbeat(machine_id: str, body: ControlRequest):
        return world.heartbeat(machine_id, **body.model_dump())

    @app.delete("/api/machines/{machine_id}/control")
    def release(machine_id: str, body: ControlRequest):
        return world.release(machine_id, **body.model_dump())

    @app.post("/api/machines/{machine_id}/commands")
    def command(machine_id: str, body: CommandRequest):
        return world.command(machine_id, **body.model_dump())

    @app.post("/api/material/scene")
    def material_scene(body: MaterialSceneRequest):
        result = world.command(body.machine_id, body.client_id, body.token, body.generation,
                               body.command_id, body.command_seq, "reset_material",
                               dict(mode=body.mode, confirm=body.confirm,
                                    controls=[control.model_dump() for control in body.controls]))
        return result["material"]

    @app.get("/api/material/config")
    def material_config():
        return world.material.config

    @app.get("/api/material/grid")
    def material_grid():
        return world.material_grid()

    @app.get("/api/geometry/config")
    def geometry_config():
        return world.geometry.config

    @app.get("/api/machines/{machine_id}/geometry")
    def machine_geometry(machine_id: str):
        return world.machine_geometry(machine_id)

    return app


app = create_app()
