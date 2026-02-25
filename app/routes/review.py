from bson import ObjectId
from fastapi import APIRouter, HTTPException

from app.db import get_db
from app.models.review import ReviewCreate, ReviewResponse
from app.models.vocab import vocab_doc_to_out
from app.services.srs_sm2 import Sm2State, apply_review
from app.services.typing_judge import is_near_correct
from app.utils.time import now_local

router = APIRouter(prefix="/review", tags=["review"])


@router.post("", response_model=ReviewResponse)
async def submit_review(payload: ReviewCreate):
    db = get_db()

    if not ObjectId.is_valid(payload.vocabId):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")

    vocab_id = ObjectId(payload.vocabId)
    vocab = await db.vocabs.find_one({"_id": vocab_id})
    if not vocab:
        raise HTTPException(status_code=404, detail="Vocab not found")

    near_correct = None
    if payload.mode == "typing" and payload.userAnswer:
        if payload.questionType == "term_to_meaning":
            candidates = vocab.get("meanings", [])
        else:
            candidates = [vocab.get("term", "")]
        near_correct = is_near_correct(payload.userAnswer, candidates)

    now = now_local()
    await db.review_logs.insert_one(
        {
            "vocabId": vocab_id,
            "mode": payload.mode,
            "questionType": payload.questionType,
            "grade": payload.grade,
            "userAnswer": payload.userAnswer,
            "isNearCorrect": near_correct,
            "createdAt": now,
        }
    )

    sm2_update = apply_review(Sm2State.from_doc(vocab), payload.grade, now)
    await db.vocabs.update_one({"_id": vocab_id}, {"$set": {**sm2_update, "updatedAt": now}})

    updated = await db.vocabs.find_one({"_id": vocab_id})
    return {
        "vocab": vocab_doc_to_out(updated).model_dump(),
        "nextDueAt": updated["dueAt"],
        "intervalDays": int(updated.get("intervalDays", 0)),
        "easeFactor": float(updated.get("easeFactor", 2.5)),
        "repetitions": int(updated.get("repetitions", 0)),
        "lapses": int(updated.get("lapses", 0)),
    }
