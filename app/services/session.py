from collections import OrderedDict
from typing import Any

from bson import ObjectId

from app.db import get_db
from app.models.vocab import vocab_doc_to_out
from app.utils.time import now_local, today_bounds, yesterday_bounds


def _to_output(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [vocab_doc_to_out(doc).model_dump() for doc in docs]


async def get_today_session(limit: int = 30) -> dict[str, list[dict[str, Any]]]:
    db = get_db()
    now = now_local()
    today_start, today_end = today_bounds()
    y_start, y_end = yesterday_bounds()

    today_new_docs = await db.vocabs.find({"createdAt": {"$gte": today_start, "$lt": today_end}}).sort("createdAt", 1).to_list(length=None)
    today_ids = {doc["_id"] for doc in today_new_docs}

    due_docs = await db.vocabs.find(
        {
            "dueAt": {"$lte": now},
            "_id": {"$nin": list(today_ids)},
        }
    ).sort("dueAt", 1).limit(limit).to_list(length=limit)

    low_grade_ids_raw = await db.review_logs.distinct(
        "vocabId",
        {"createdAt": {"$gte": y_start, "$lt": y_end}, "grade": {"$lt": 3}},
    )
    low_grade_ids: list[ObjectId] = [item for item in low_grade_ids_raw if isinstance(item, ObjectId)]

    yesterday_not_mastered_query: dict[str, Any] = {
        "lastReviewedAt": {"$gte": y_start, "$lt": y_end},
        "_id": {"$nin": list(today_ids)},
        "$or": [
            {"_id": {"$in": low_grade_ids}},
            {"readdCount": {"$gt": 0}},
            {
                "$and": [
                    {"lapses": {"$gt": 0}},
                    {"updatedAt": {"$gte": y_start, "$lt": y_end}},
                ]
            },
        ],
    }

    yesterday_not_mastered_docs = await db.vocabs.find(yesterday_not_mastered_query).sort("lastReviewedAt", 1).limit(limit).to_list(length=limit)

    struggle_docs = await db.vocabs.find(
        {
            "readdCount": {"$gt": 0},
            "_id": {"$nin": list(today_ids)},
        }
    ).sort([("readdCount", -1), ("dueAt", 1)]).limit(limit).to_list(length=limit)

    ordered_review: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for bucket in (due_docs, yesterday_not_mastered_docs, struggle_docs):
        for doc in bucket:
            key = str(doc["_id"])
            if key in ordered_review:
                continue
            ordered_review[key] = doc
            if len(ordered_review) >= limit:
                break
        if len(ordered_review) >= limit:
            break

    return {
        "todayNew": _to_output(today_new_docs),
        "review": _to_output(list(ordered_review.values())),
    }
