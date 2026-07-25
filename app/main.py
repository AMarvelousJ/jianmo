from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import axis, loader, path_plans, path_tasks, scene, simulation, state

app = FastAPI(title="Shiploader Motion Simulation API", version="0.1.0")
app.include_router(simulation.router)
app.include_router(axis.router)
app.include_router(state.router)
app.include_router(scene.router)
app.include_router(loader.router)
app.include_router(path_plans.router)
app.include_router(path_tasks.router)


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
