from fastapi import APIRouter, Query

from app.models.vocab import SessionOut
from app.services.session import get_today_session

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/today", response_model=SessionOut)
async def session_today(limit: int = Query(default=30, ge=1, le=200)):
    payload = await get_today_session(limit=limit)
    return payload
