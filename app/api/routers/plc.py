from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_plc_sync_service
from app.core.plc.sync_service import PlcSyncService
from app.models.plc import PlcStatus

router = APIRouter(prefix="/api/plc", tags=["plc"])


@router.get("/status", response_model=PlcStatus)
def get_plc_status(
    service: PlcSyncService = Depends(get_plc_sync_service),
) -> PlcStatus:
    return service.status()
