from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.config import get_settings, validate_mongo_settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        settings = validate_mongo_settings(get_settings())
        _client = AsyncIOMotorClient(
            settings.mongo_url,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        settings = validate_mongo_settings(get_settings())
        _db = get_client()[settings.mongo_db]
    return _db


async def ping_db() -> None:
    await get_client().admin.command("ping")


async def create_indexes() -> None:
    db = get_db()
    await db.vocabs.create_index([("termNormalized", ASCENDING)], unique=True, name="uq_vocabs_term_normalized")
    await db.vocabs.create_index([("dueAt", ASCENDING)], name="idx_vocabs_due_at")
    await db.vocabs.create_index([("topics", ASCENDING)], name="idx_vocabs_topics")
    await db.vocabs.create_index([("cefrLevel", ASCENDING)], name="idx_vocabs_cefr")
    await db.review_logs.create_index(
        [("vocabId", ASCENDING), ("createdAt", DESCENDING)],
        name="idx_review_logs_vocab_created",
    )
    await db.ai_cache.create_index([("key", ASCENDING)], unique=True, name="uq_ai_cache_key")
    await db.practice_logs.create_index([("createdAt", DESCENDING)], name="idx_practice_logs_created")
    await db.practice_logs.create_index([("vocabId", ASCENDING), ("createdAt", DESCENDING)], name="idx_practice_logs_vocab_created")
    await db.writing_errors.create_index([("key", ASCENDING)], unique=True, name="uq_writing_errors_key")
    await db.writing_errors.create_index([("count", DESCENDING), ("updatedAt", DESCENDING)], name="idx_writing_errors_count_updated")
    await db.topic_packs.create_index([("name", ASCENDING)], unique=True, name="uq_topic_packs_name")
