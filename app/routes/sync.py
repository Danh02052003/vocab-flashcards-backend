from fastapi import APIRouter, HTTPException

from app.models.sync import SyncExport, SyncImportReport
from app.services.sync_merge import export_payload, import_payload

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/export", response_model=SyncExport)
async def export_sync():
    payload = await export_payload()
    return SyncExport(**payload)


@router.post("/import", response_model=SyncImportReport)
async def import_sync(payload: SyncExport):
    if payload.schemaVersion != "v1":
        raise HTTPException(status_code=400, detail="Unsupported schemaVersion")
    report = await import_payload(payload.model_dump())
    return SyncImportReport(**report)
