from fastapi import APIRouter, Query

from app.models.vocab import SessionOut
from app.services.auth import CurrentUser
from app.services.session import get_today_session

router = APIRouter(prefix="/session", tags=["session"])


@router.get("/today", response_model=SessionOut)
async def session_today(limit: int = Query(default=30, ge=1, le=200), current_user=CurrentUser):
    payload = await get_today_session(user_id=current_user["_id"], limit=limit)
    return payload
