import re
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from app.db import get_db
from app.models.practice import (
    ClozeGenerateRequest,
    ClozeGenerateResponse,
    ClozeItem,
    ClozeSubmitRequest,
    ClozeSubmitResponse,
    SpeakingFeedbackRequest,
    SpeakingFeedbackResponse,
)
from app.services.ai_provider import StubAiProvider, get_ai_provider
from app.services.typing_judge import is_near_correct
from app.utils.time import now_local

router = APIRouter(prefix="/practice", tags=["practice"])


def _parse_object_id(raw: str) -> ObjectId:
    if not ObjectId.is_valid(raw):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")
    return ObjectId(raw)


def _build_cloze_question(term: str, example: str | None, meaning: str | None) -> tuple[str, str | None]:
    cleaned_term = str(term).strip()
    if example:
        pattern = re.compile(re.escape(cleaned_term), re.IGNORECASE)
        if pattern.search(example):
            return pattern.sub("____", example, count=1), f"Meaning: {meaning}" if meaning else None
    return f"Fill in the blank: ____ means '{meaning or ''}'.", None


@router.post("/cloze/generate", response_model=ClozeGenerateResponse)
async def generate_cloze(payload: ClozeGenerateRequest):
    db = get_db()
    query: dict[str, Any] = {}

    if payload.vocabIds:
        oids = [_parse_object_id(v) for v in payload.vocabIds]
        query["_id"] = {"$in": oids}
    elif payload.topic:
        query["topics"] = payload.topic

    docs = await db.vocabs.find(query).sort("updatedAt", -1).limit(payload.limit).to_list(length=payload.limit)
    if not docs:
        docs = await db.vocabs.find({}).sort("dueAt", 1).limit(payload.limit).to_list(length=payload.limit)

    items: list[ClozeItem] = []
    for doc in docs:
        term = str(doc.get("term", "")).strip()
        if not term:
            continue
        meaning = (doc.get("meanings") or [None])[0]
        question, hint = _build_cloze_question(term, doc.get("exampleEn"), meaning)
        items.append(
            ClozeItem(
                vocabId=str(doc["_id"]),
                term=term,
                ipa=doc.get("ipa"),
                question=question,
                hint=hint,
                acceptableAnswers=[term] + (doc.get("phrases") or []),
            )
        )

    return ClozeGenerateResponse(items=items)


@router.post("/cloze/submit", response_model=ClozeSubmitResponse)
async def submit_cloze(payload: ClozeSubmitRequest):
    db = get_db()
    oid = _parse_object_id(payload.vocabId)
    vocab = await db.vocabs.find_one({"_id": oid})
    if not vocab:
        raise HTTPException(status_code=404, detail="Vocab not found")

    candidates = [vocab.get("term", "")] + (vocab.get("phrases") or [])
    near = is_near_correct(payload.userAnswer, candidates)
    normalized_answer = payload.userAnswer.strip().lower()
    exact = normalized_answer == str(vocab.get("term", "")).strip().lower()

    await db.practice_logs.insert_one(
        {
            "type": "cloze_submit",
            "vocabId": oid,
            "correct": bool(exact),
            "nearCorrect": bool(near),
            "userAnswer": payload.userAnswer,
            "createdAt": now_local(),
        }
    )

    return ClozeSubmitResponse(correct=bool(exact), nearCorrect=bool(near), expected=str(vocab.get("term", "")))


@router.post("/speaking_feedback", response_model=SpeakingFeedbackResponse)
async def speaking_feedback(payload: SpeakingFeedbackRequest):
    provider = get_ai_provider()
    provider_used = provider.provider_name
    try:
        feedback = await provider.speaking_feedback(
            prompt=payload.prompt,
            response_text=payload.responseText,
            target_words=payload.targetWords,
        )
    except Exception:
        fallback = StubAiProvider()
        feedback = await fallback.speaking_feedback(
            prompt=payload.prompt,
            response_text=payload.responseText,
            target_words=payload.targetWords,
        )
        provider_used = fallback.provider_name

    now = now_local()
    db = get_db()
    await db.practice_logs.insert_one(
        {
            "type": "speaking_feedback",
            "prompt": payload.prompt,
            "responseText": payload.responseText,
            "targetWords": payload.targetWords,
            "feedback": feedback,
            "provider": provider_used,
            "createdAt": now,
        }
    )

    return SpeakingFeedbackResponse(
        estimatedBand=float(feedback.get("estimatedBand", 5.0)),
        targetCoverage=float(feedback.get("targetCoverage", 0.0)),
        usedTargetWords=feedback.get("usedTargetWords", []) or [],
        strengths=feedback.get("strengths", []) or [],
        improvements=feedback.get("improvements", []) or [],
        reasonShort=str(feedback.get("reasonShort", "speaking feedback")),
        provider=provider_used,
        createdAt=now,
    )
