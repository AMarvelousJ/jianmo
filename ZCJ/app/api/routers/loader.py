from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_loader_profile
from app.models.loader_config import LoaderProfile

router = APIRouter(prefix="/api/loader", tags=["loader"])


@router.get("/config", response_model=LoaderProfile)
def get_loader_config(profile: LoaderProfile = Depends(get_loader_profile)) -> LoaderProfile:
    return profile
