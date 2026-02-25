from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models.pack import TopicPackAddVocabRequest, TopicPackCreate, TopicPackOut
from app.models.vocab import vocab_doc_to_out
from app.utils.time import now_local

router = APIRouter(prefix="/packs", tags=["packs"])


def _unique_strings(items: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _to_out(doc: dict[str, Any]) -> TopicPackOut:
    return TopicPackOut(
        id=str(doc["_id"]),
        name=doc.get("name", ""),
        description=doc.get("description"),
        topics=doc.get("topics", []) or [],
        targetBand=doc.get("targetBand"),
        vocabIds=doc.get("vocabIds", []) or [],
        createdAt=doc.get("createdAt"),
        updatedAt=doc.get("updatedAt"),
    )


@router.post("", response_model=TopicPackOut)
async def create_pack(payload: TopicPackCreate):
    db = get_db()
    now = now_local()

    vocab_ids: list[str] = []
    for item in payload.vocabIds:
        if not ObjectId.is_valid(item):
            raise HTTPException(status_code=400, detail=f"Invalid vocabId: {item}")
        exists = await db.vocabs.find_one({"_id": ObjectId(item)}, {"_id": 1})
        if exists:
            vocab_ids.append(item)

    doc = {
        "name": payload.name.strip(),
        "description": payload.description,
        "topics": _unique_strings(payload.topics),
        "targetBand": payload.targetBand,
        "vocabIds": _unique_strings(vocab_ids),
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        result = await db.topic_packs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Pack name already exists")
    created = await db.topic_packs.find_one({"_id": result.inserted_id})
    return _to_out(created)


@router.get("", response_model=list[TopicPackOut])
async def list_packs(page: int = Query(default=1, ge=1), limit: int = Query(default=20, ge=1, le=200)):
    db = get_db()
    skip = (page - 1) * limit
    docs = await db.topic_packs.find({}).sort("updatedAt", -1).skip(skip).limit(limit).to_list(length=limit)
    return [_to_out(doc) for doc in docs]


@router.get("/{pack_id}", response_model=TopicPackOut)
async def get_pack(pack_id: str):
    if not ObjectId.is_valid(pack_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")
    db = get_db()
    doc = await db.topic_packs.find_one({"_id": ObjectId(pack_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Pack not found")
    return _to_out(doc)


@router.post("/{pack_id}/add_vocab", response_model=TopicPackOut)
async def add_vocab_to_pack(pack_id: str, payload: TopicPackAddVocabRequest):
    if not ObjectId.is_valid(pack_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")
    if not ObjectId.is_valid(payload.vocabId):
        raise HTTPException(status_code=400, detail="Invalid vocabId")

    db = get_db()
    pack = await db.topic_packs.find_one({"_id": ObjectId(pack_id)})
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    vocab = await db.vocabs.find_one({"_id": ObjectId(payload.vocabId)}, {"_id": 1})
    if not vocab:
        raise HTTPException(status_code=404, detail="Vocab not found")

    updated_ids = _unique_strings((pack.get("vocabIds") or []) + [payload.vocabId])
    await db.topic_packs.update_one(
        {"_id": pack["_id"]},
        {"$set": {"vocabIds": updated_ids, "updatedAt": now_local()}},
    )
    updated = await db.topic_packs.find_one({"_id": pack["_id"]})
    return _to_out(updated)


@router.get("/{pack_id}/session")
async def get_pack_session(pack_id: str, limit: int = Query(default=20, ge=1, le=100)):
    if not ObjectId.is_valid(pack_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")

    db = get_db()
    pack = await db.topic_packs.find_one({"_id": ObjectId(pack_id)})
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")

    vocab_ids = [ObjectId(v) for v in (pack.get("vocabIds") or []) if ObjectId.is_valid(v)]
    if not vocab_ids:
        return {"pack": _to_out(pack).model_dump(), "vocabs": []}

    vocabs = await db.vocabs.find({"_id": {"$in": vocab_ids}}).sort("dueAt", 1).limit(limit).to_list(length=limit)
    return {
        "pack": _to_out(pack).model_dump(),
        "vocabs": [vocab_doc_to_out(v).model_dump() for v in vocabs],
    }
