from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query

from app.db import get_db
from app.models.writing import (
    WritingDeckItem,
    WritingDeckResponse,
    WritingErrorCreate,
    WritingErrorOut,
)
from app.services.auth import CurrentUser
from app.utils.hash import stable_hash
from app.utils.time import now_local

router = APIRouter(prefix="/writing", tags=["writing"])


def _to_out(doc: dict[str, Any]) -> WritingErrorOut:
    return WritingErrorOut(
        id=str(doc["_id"]),
        sentence=doc.get("sentence", ""),
        correctedSentence=doc.get("correctedSentence", ""),
        category=doc.get("category", "grammar"),
        notes=doc.get("notes"),
        topic=doc.get("topic"),
        count=int(doc.get("count", 1)),
        createdAt=doc.get("createdAt"),
        updatedAt=doc.get("updatedAt"),
    )


@router.post("/error-bank", response_model=WritingErrorOut)
async def add_writing_error(payload: WritingErrorCreate, current_user=CurrentUser):
    db = get_db()
    now = now_local()

    key = stable_hash(
        {
            "sentence": payload.sentence.strip().lower(),
            "corrected": payload.correctedSentence.strip().lower(),
            "category": payload.category,
        }
    )

    existing = await db.writing_errors.find_one({"key": key, "userId": current_user["_id"]})
    if existing:
        await db.writing_errors.update_one(
            {"_id": existing["_id"], "userId": current_user["_id"]},
            {
                "$set": {
                    "notes": payload.notes,
                    "topic": payload.topic,
                    "updatedAt": now,
                },
                "$inc": {"count": 1},
            },
        )
        updated = await db.writing_errors.find_one({"_id": existing["_id"], "userId": current_user["_id"]})
        return _to_out(updated)

    doc = {
        "userId": current_user["_id"],
        "key": key,
        "sentence": payload.sentence.strip(),
        "correctedSentence": payload.correctedSentence.strip(),
        "category": payload.category,
        "notes": payload.notes,
        "topic": payload.topic,
        "count": 1,
        "createdAt": now,
        "updatedAt": now,
    }
    result = await db.writing_errors.insert_one(doc)
    created = await db.writing_errors.find_one({"_id": result.inserted_id, "userId": current_user["_id"]})
    return _to_out(created)


@router.get("/error-bank", response_model=list[WritingErrorOut])
async def list_writing_errors(
    category: str | None = None,
    topic: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    current_user=CurrentUser,
):
    db = get_db()
    query: dict[str, Any] = {"userId": current_user["_id"]}
    if category:
        query["category"] = category
    if topic:
        query["topic"] = topic

    skip = (page - 1) * limit
    docs = await db.writing_errors.find(query).sort([("count", -1), ("updatedAt", -1)]).skip(skip).limit(limit).to_list(length=limit)
    return [_to_out(doc) for doc in docs]


@router.get("/error-bank/deck", response_model=WritingDeckResponse)
async def get_writing_error_deck(limit: int = Query(default=10, ge=1, le=100), current_user=CurrentUser):
    db = get_db()
    docs = await db.writing_errors.find({"userId": current_user["_id"]}).sort([("count", -1), ("updatedAt", -1)]).limit(limit).to_list(length=limit)
    items = [
        WritingDeckItem(
            id=str(doc["_id"]),
            sentence=doc.get("sentence", ""),
            correctedSentence=doc.get("correctedSentence", ""),
            category=doc.get("category", "grammar"),
        )
        for doc in docs
    ]
    return WritingDeckResponse(items=items)


@router.delete("/error-bank/{error_id}")
async def delete_writing_error(error_id: str, current_user=CurrentUser):
    if not ObjectId.is_valid(error_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")
    db = get_db()
    result = await db.writing_errors.delete_one({"_id": ObjectId(error_id), "userId": current_user["_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Error item not found")
    return {"deleted": True}
