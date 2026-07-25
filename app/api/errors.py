from __future__ import annotations

from fastapi import HTTPException

from app.core.path_planning.errors import PathPlanningError


def path_http_exception(error: PathPlanningError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail())
