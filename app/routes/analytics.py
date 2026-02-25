from collections import defaultdict
from datetime import timedelta

from bson import ObjectId
from fastapi import APIRouter, Query

from app.db import get_db
from app.models.analytics import AnalyticsOverview, TopicStat
from app.utils.time import now_local

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(days: int = Query(default=30, ge=1, le=365)):
    db = get_db()
    now = now_local()
    start = now - timedelta(days=days)

    total_vocabs = await db.vocabs.count_documents({})
    due_now = await db.vocabs.count_documents({"dueAt": {"$lte": now}})

    logs = await db.review_logs.find({"createdAt": {"$gte": start}}).to_list(length=None)
    reviewed_count = len(logs)
    avg_grade = round(sum(int(log.get("grade", 0)) for log in logs) / reviewed_count, 2) if reviewed_count else 0.0
    accuracy_rate = (
        round(sum(1 for log in logs if int(log.get("grade", 0)) >= 3) / reviewed_count, 2) if reviewed_count else 0.0
    )

    typing_logs = [log for log in logs if log.get("mode") == "typing"]
    typing_accuracy = (
        round(sum(1 for log in typing_logs if int(log.get("grade", 0)) >= 3) / len(typing_logs), 2)
        if typing_logs
        else 0.0
    )

    return AnalyticsOverview(
        days=days,
        totalVocabs=total_vocabs,
        dueNow=due_now,
        reviewedCount=reviewed_count,
        avgGrade=avg_grade,
        accuracyRate=accuracy_rate,
        typingAccuracy=typing_accuracy,
    )


@router.get("/topics", response_model=list[TopicStat])
async def analytics_topics(days: int = Query(default=30, ge=1, le=365)):
    db = get_db()
    now = now_local()
    start = now - timedelta(days=days)

    vocab_docs = await db.vocabs.find({}, {"topics": 1}).to_list(length=None)
    vocab_topics: dict[str, list[str]] = {}
    topic_vocab_count: defaultdict[str, int] = defaultdict(int)

    for doc in vocab_docs:
        topics = [str(t).strip() for t in (doc.get("topics") or []) if str(t).strip()]
        vocab_topics[str(doc["_id"])] = topics
        for topic in topics:
            topic_vocab_count[topic] += 1

    logs = await db.review_logs.find({"createdAt": {"$gte": start}}).to_list(length=None)
    topic_review_count: defaultdict[str, int] = defaultdict(int)
    topic_grade_sum: defaultdict[str, int] = defaultdict(int)

    for log in logs:
        vid = log.get("vocabId")
        vid_key = str(vid) if isinstance(vid, ObjectId) else str(vid)
        topics = vocab_topics.get(vid_key, [])
        for topic in topics:
            topic_review_count[topic] += 1
            topic_grade_sum[topic] += int(log.get("grade", 0))

    all_topics = set(topic_vocab_count.keys()) | set(topic_review_count.keys())
    stats: list[TopicStat] = []
    for topic in sorted(all_topics):
        reviewed = topic_review_count.get(topic, 0)
        avg_grade = round(topic_grade_sum.get(topic, 0) / reviewed, 2) if reviewed else 0.0
        stats.append(
            TopicStat(
                topic=topic,
                vocabCount=topic_vocab_count.get(topic, 0),
                reviewedCount=reviewed,
                avgGrade=avg_grade,
            )
        )

    return stats
