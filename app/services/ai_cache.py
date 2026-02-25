from datetime import datetime
from typing import Any

from app.db import get_db
from app.utils.hash import stable_hash

CACHE_VERSION = "v1"


def _merge_list_unique(a: list[Any] | None, b: list[Any] | None) -> list[Any]:
    seen: set[str] = set()
    merged: list[Any] = []
    for item in (a or []) + (b or []):
        key = stable_hash(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def merge_ai_data(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(existing or {})
    for key in ("examples", "mnemonics", "meaningVariants", "synonymGroups", "distractors"):
        if key in incoming:
            merged[key] = _merge_list_unique(merged.get(key), incoming.get(key))

    if "judge" in incoming:
        merged["judge"] = incoming["judge"]
    if "ipa" in incoming and str(incoming.get("ipa") or "").strip():
        merged["ipa"] = str(incoming["ipa"]).strip()

    return merged


async def get_cache(key: str) -> dict[str, Any] | None:
    db = get_db()
    return await db.ai_cache.find_one({"key": key})


async def upsert_cache(
    *,
    key: str,
    term_normalized: str,
    provider: str,
    data: dict[str, Any],
    now: datetime,
    version: str = CACHE_VERSION,
) -> dict[str, Any]:
    db = get_db()
    await db.ai_cache.update_one(
        {"key": key},
        {
            "$set": {
                "termNormalized": term_normalized,
                "version": version,
                "provider": provider,
                "data": data,
                "updatedAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    return await db.ai_cache.find_one({"key": key})
