from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers import axis, scene, simulation, state

app = FastAPI(title="Shiploader Motion Simulation API", version="0.1.0")
app.include_router(simulation.router)
app.include_router(axis.router)
app.include_router(state.router)
app.include_router(scene.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
