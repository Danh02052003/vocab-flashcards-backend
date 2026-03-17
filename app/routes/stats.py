from typing import Any

from fastapi import APIRouter

from app.db import get_db
from app.models.stats import (
    ReviewCompletedRequest,
    StudyLockCompletedRequest,
    StudySettingsRequest,
    UserStatsOut,
    VocabCreatedRequest,
)
from app.services.auth import CurrentUser
from app.utils.time import now_local

router = APIRouter(prefix="/stats", tags=["stats"])


def _today_key() -> str:
    return now_local().date().isoformat()


def _default_stats() -> dict[str, Any]:
    today = _today_key()
    return {
        "streak": 0,
        "lastActivityDate": "",
        "totalReviewed": 0,
        "totalCorrect": 0,
        "accuracy": 0,
        "dailyNewCreatedCount": 0,
        "dailyNewCreatedDate": today,
        "dailyStudyLockCompletedCount": 0,
        "dailyStudyLockCompletedDate": today,
        "studyLockTargetPerDay": 5,
        "studyLockIntervalMinutes": 45,
    }


async def _get_or_create_stats(user_id):
    db = get_db()
    doc = await db.user_stats.find_one({"userId": user_id})
    if doc:
        return doc
    base = {"userId": user_id, **_default_stats(), "createdAt": now_local(), "updatedAt": now_local()}
    await db.user_stats.insert_one(base)
    return await db.user_stats.find_one({"userId": user_id})


async def _save_stats(user_id, data: dict[str, Any]):
    db = get_db()
    payload = {**data, "updatedAt": now_local()}
    await db.user_stats.update_one({"userId": user_id}, {"$set": payload}, upsert=True)
    return await db.user_stats.find_one({"userId": user_id})


def _apply_streak(stats: dict[str, Any]) -> dict[str, Any]:
    today = _today_key()
    yesterday = (now_local().date()).fromordinal(now_local().date().toordinal() - 1).isoformat()
    last = str(stats.get("lastActivityDate") or "")
    if last == today:
        return stats
    next_streak = 1 if last not in (yesterday,) else int(stats.get("streak", 0)) + 1
    return {**stats, "streak": next_streak, "lastActivityDate": today}


def _to_out(doc: dict[str, Any]) -> UserStatsOut:
    return UserStatsOut(
        streak=int(doc.get("streak", 0)),
        lastActivityDate=str(doc.get("lastActivityDate") or ""),
        totalReviewed=int(doc.get("totalReviewed", 0)),
        totalCorrect=int(doc.get("totalCorrect", 0)),
        accuracy=int(doc.get("accuracy", 0)),
        dailyNewCreatedCount=int(doc.get("dailyNewCreatedCount", 0)),
        dailyNewCreatedDate=str(doc.get("dailyNewCreatedDate") or ""),
        dailyStudyLockCompletedCount=int(doc.get("dailyStudyLockCompletedCount", 0)),
        dailyStudyLockCompletedDate=str(doc.get("dailyStudyLockCompletedDate") or ""),
        studyLockTargetPerDay=int(doc.get("studyLockTargetPerDay", 5)),
        studyLockIntervalMinutes=int(doc.get("studyLockIntervalMinutes", 45)),
    )


def _roll_daily_counters(stats: dict[str, Any]) -> dict[str, Any]:
    today = _today_key()
    next_stats = dict(stats)
    if str(next_stats.get("dailyNewCreatedDate") or "") != today:
        next_stats["dailyNewCreatedDate"] = today
        next_stats["dailyNewCreatedCount"] = 0
    if str(next_stats.get("dailyStudyLockCompletedDate") or "") != today:
        next_stats["dailyStudyLockCompletedDate"] = today
        next_stats["dailyStudyLockCompletedCount"] = 0
    return next_stats


@router.get("", response_model=UserStatsOut)
async def get_stats(current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    stats = _roll_daily_counters(stats)
    stats = await _save_stats(current_user["_id"], {k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}})
    return _to_out(stats)


@router.post("/review_started", response_model=UserStatsOut)
async def review_started(current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    stats = _roll_daily_counters(stats)
    stats = _apply_streak(stats)
    stats = await _save_stats(current_user["_id"], {k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}})
    return _to_out(stats)


@router.post("/review_completed", response_model=UserStatsOut)
async def review_completed(payload: ReviewCompletedRequest, current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    total_reviewed = int(stats.get("totalReviewed", 0)) + payload.total
    total_correct = int(stats.get("totalCorrect", 0)) + payload.passed
    accuracy = round((total_correct / total_reviewed) * 100) if total_reviewed > 0 else 0
    stats = await _save_stats(
        current_user["_id"],
        {
            **{k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}},
            "totalReviewed": total_reviewed,
            "totalCorrect": total_correct,
            "accuracy": accuracy,
        },
    )
    return _to_out(stats)


@router.post("/vocab_created", response_model=UserStatsOut)
async def vocab_created(payload: VocabCreatedRequest, current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    stats = _roll_daily_counters(stats)
    next_count = int(stats.get("dailyNewCreatedCount", 0)) + payload.count
    stats["dailyNewCreatedCount"] = next_count
    if next_count >= 5:
        stats = _apply_streak(stats)
    stats = await _save_stats(current_user["_id"], {k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}})
    return _to_out(stats)


@router.post("/study_lock_completed", response_model=UserStatsOut)
async def study_lock_completed(payload: StudyLockCompletedRequest, current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    stats = _roll_daily_counters(stats)
    next_count = int(stats.get("dailyStudyLockCompletedCount", 0)) + payload.count
    stats["dailyStudyLockCompletedCount"] = next_count
    if next_count >= int(stats.get("studyLockTargetPerDay", 5)):
        stats = _apply_streak(stats)
    stats = await _save_stats(current_user["_id"], {k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}})
    return _to_out(stats)


@router.post("/settings", response_model=UserStatsOut)
async def update_settings(payload: StudySettingsRequest, current_user=CurrentUser):
    stats = await _get_or_create_stats(current_user["_id"])
    stats = await _save_stats(
        current_user["_id"],
        {
            **{k: v for k, v in stats.items() if k not in {"_id", "userId", "createdAt", "updatedAt"}},
            "studyLockTargetPerDay": payload.studyLockTargetPerDay,
            "studyLockIntervalMinutes": payload.studyLockIntervalMinutes,
        },
    )
    return _to_out(stats)

