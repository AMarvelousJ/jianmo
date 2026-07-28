from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.dependencies import get_plc_sync_service
from app.api.routers import (
    axis,
    loader,
    loading_plans,
    loading_tasks,
    path_plans,
    path_tasks,
    plc,
    scene,
    simulation,
    state,
)
from app.core.loading.errors import LoadingError


@asynccontextmanager
async def lifespan(_: FastAPI):
    plc_sync_service = get_plc_sync_service()
    plc_sync_service.start()
    try:
        yield
    finally:
        plc_sync_service.stop()


app = FastAPI(
    title="Shiploader Motion Simulation API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(simulation.router)
app.include_router(axis.router)
app.include_router(state.router)
app.include_router(scene.router)
app.include_router(loader.router)
app.include_router(path_plans.router)
app.include_router(path_tasks.router)
app.include_router(loading_plans.router)
app.include_router(loading_tasks.router)
app.include_router(plc.router)


@app.exception_handler(LoadingError)
async def loading_exception_handler(
    _: Request,
    error: LoadingError,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.detail()},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    issues = [
        {
            "field": ".".join(str(part) for part in issue["loc"] if part != "body"),
            "message": issue["msg"],
            "type": issue["type"],
        }
        for issue in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败。",
                "context": {
                    "method": request.method,
                    "path": request.url.path,
                    "errors": issues,
                },
            }
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
