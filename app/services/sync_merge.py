from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from app.db import get_db
from app.utils.hash import stable_hash
from app.utils.normalize import normalize_term
from app.utils.time import now_local


def _parse_datetime(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, str):
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return default

    return default


def _serialize_value(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _serialize_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize_value(value) for key, value in doc.items()}


def _merge_unique_strings(a: list[str] | None, b: list[str] | None) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in (a or []) + (b or []):
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    return merged


def _normalize_word_family(data: dict[str, list[str]] | None) -> dict[str, list[str]]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, values in data.items():
        role = str(key).strip().lower()
        if not role:
            continue
        out[role] = _merge_unique_strings(values or [], [])
    return out


def _merge_word_family(left: dict[str, list[str]] | None, right: dict[str, list[str]] | None) -> dict[str, list[str]]:
    merged = _normalize_word_family(left)
    right_norm = _normalize_word_family(right)
    for role, vals in right_norm.items():
        merged[role] = _merge_unique_strings(merged.get(role, []), vals)
    return merged


def _log_dedup_hash(log: dict[str, Any]) -> str:
    return stable_hash(
        {
            "vocabId": str(log.get("vocabId")),
            "createdAt": _serialize_value(log.get("createdAt")),
            "grade": int(log.get("grade", 0)),
            "mode": str(log.get("mode", "flip")),
            "questionType": str(log.get("questionType", "term_to_meaning")),
        }
    )


def _safe_min_datetime(left: datetime | None, right: datetime | None, fallback: datetime) -> datetime:
    if left is None and right is None:
        return fallback
    if left is None:
        return right or fallback
    if right is None:
        return left
    return min(left, right)


def _safe_max_datetime(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


async def export_payload() -> dict[str, Any]:
    db = get_db()
    now = now_local()

    await db.events.insert_one(
        {
            "type": "EXPORT",
            "payload": {"schemaVersion": "v1"},
            "createdAt": now,
        }
    )

    vocabs = await db.vocabs.find({}).sort([("termNormalized", 1), ("createdAt", 1)]).to_list(length=None)
    review_logs = await db.review_logs.find({}).sort([("createdAt", 1)]).to_list(length=None)
    events = await db.events.find({}).sort([("createdAt", 1)]).to_list(length=None)

    return {
        "schemaVersion": "v1",
        "exportedAt": now,
        "vocabs": [_serialize_doc(doc) for doc in vocabs],
        "review_logs": [_serialize_doc(doc) for doc in review_logs],
        "events": [_serialize_doc(doc) for doc in events],
    }


async def import_payload(payload: dict[str, Any]) -> dict[str, int]:
    db = get_db()
    now = now_local()

    added_vocabs = 0
    updated_vocabs = 0
    added_logs = 0
    conflicts = 0

    source_vocab_to_local: dict[str, ObjectId] = {}

    incoming_vocabs = payload.get("vocabs", []) or []
    incoming_vocabs.sort(
        key=lambda doc: normalize_term(str(doc.get("termNormalized") or doc.get("term") or ""))
    )

    for incoming in incoming_vocabs:
        term_norm = normalize_term(str(incoming.get("termNormalized") or incoming.get("term") or ""))
        if not term_norm:
            continue

        source_vocab_id = str(incoming.get("_id") or "")
        incoming_updated = _parse_datetime(incoming.get("updatedAt"), now)
        incoming_created = _parse_datetime(incoming.get("createdAt"), now)

        incoming_doc = {
            "term": str(incoming.get("term") or term_norm),
            "termNormalized": term_norm,
            "meanings": _merge_unique_strings(incoming.get("meanings") or [], []),
            "ipa": (str(incoming.get("ipa")).strip() if incoming.get("ipa") is not None else None),
            "exampleEn": (incoming.get("exampleEn") or None),
            "exampleVi": (incoming.get("exampleVi") or None),
            "mnemonic": (incoming.get("mnemonic") or None),
            "tags": _merge_unique_strings(incoming.get("tags") or [], []),
            "collocations": _merge_unique_strings(incoming.get("collocations") or [], []),
            "phrases": _merge_unique_strings(incoming.get("phrases") or [], []),
            "wordFamily": _normalize_word_family(incoming.get("wordFamily") or {}),
            "topics": _merge_unique_strings(incoming.get("topics") or [], []),
            "cefrLevel": incoming.get("cefrLevel"),
            "ieltsBand": float(incoming.get("ieltsBand")) if incoming.get("ieltsBand") is not None else None,
            "createdAt": incoming_created,
            "updatedAt": incoming_updated,
            "easeFactor": float(incoming.get("easeFactor", 2.5)),
            "intervalDays": int(incoming.get("intervalDays", 0)),
            "repetitions": int(incoming.get("repetitions", 0)),
            "lapses": int(incoming.get("lapses", 0)),
            "dueAt": _parse_datetime(incoming.get("dueAt"), now),
            "lastReviewedAt": _parse_datetime(incoming.get("lastReviewedAt"), now)
            if incoming.get("lastReviewedAt")
            else None,
            "readdCount": int(incoming.get("readdCount", 0)),
            "lastReaddAt": _parse_datetime(incoming.get("lastReaddAt"), now)
            if incoming.get("lastReaddAt")
            else None,
        }

        existing = await db.vocabs.find_one({"termNormalized": term_norm})
        if not existing:
            result = await db.vocabs.insert_one(incoming_doc)
            source_vocab_to_local[source_vocab_id] = result.inserted_id
            added_vocabs += 1
            continue

        source_vocab_to_local[source_vocab_id] = existing["_id"]

        merged = dict(existing)
        merged["meanings"] = _merge_unique_strings(existing.get("meanings", []), incoming_doc.get("meanings", []))
        merged["tags"] = _merge_unique_strings(existing.get("tags", []), incoming_doc.get("tags", []))
        merged["collocations"] = _merge_unique_strings(existing.get("collocations", []), incoming_doc.get("collocations", []))
        merged["phrases"] = _merge_unique_strings(existing.get("phrases", []), incoming_doc.get("phrases", []))
        merged["topics"] = _merge_unique_strings(existing.get("topics", []), incoming_doc.get("topics", []))
        merged["wordFamily"] = _merge_word_family(existing.get("wordFamily", {}), incoming_doc.get("wordFamily", {}))
        merged["cefrLevel"] = incoming_doc.get("cefrLevel") or existing.get("cefrLevel")
        merged["ieltsBand"] = (
            incoming_doc.get("ieltsBand")
            if incoming_doc.get("ieltsBand") is not None
            else existing.get("ieltsBand")
        )

        existing_updated = _parse_datetime(existing.get("updatedAt"), now)
        text_fields = ["term", "ipa", "exampleEn", "exampleVi", "mnemonic"]

        if incoming_updated >= existing_updated:
            for field in text_fields:
                existing_value = existing.get(field)
                incoming_value = incoming_doc.get(field)
                if existing_value and incoming_value and existing_value != incoming_value:
                    conflicts += 1
                if incoming_value:
                    merged[field] = incoming_value

        merged["createdAt"] = min(_parse_datetime(existing.get("createdAt"), now), incoming_created)
        merged["updatedAt"] = max(existing_updated, incoming_updated)

        merged["repetitions"] = min(int(existing.get("repetitions", 0)), incoming_doc["repetitions"])
        merged["intervalDays"] = min(int(existing.get("intervalDays", 0)), incoming_doc["intervalDays"])
        merged["easeFactor"] = min(float(existing.get("easeFactor", 2.5)), incoming_doc["easeFactor"])
        merged["dueAt"] = _safe_min_datetime(existing.get("dueAt"), incoming_doc["dueAt"], now)
        merged["lapses"] = max(int(existing.get("lapses", 0)), incoming_doc["lapses"])
        merged["readdCount"] = max(int(existing.get("readdCount", 0)), incoming_doc["readdCount"])
        merged["lastReviewedAt"] = _safe_max_datetime(existing.get("lastReviewedAt"), incoming_doc["lastReviewedAt"])
        merged["lastReaddAt"] = _safe_max_datetime(existing.get("lastReaddAt"), incoming_doc["lastReaddAt"])

        existing_serialized = _serialize_doc({k: v for k, v in existing.items() if k != "_id"})
        merged_serialized = _serialize_doc({k: v for k, v in merged.items() if k != "_id"})
        if stable_hash(existing_serialized) != stable_hash(merged_serialized):
            await db.vocabs.update_one({"_id": existing["_id"]}, {"$set": {k: v for k, v in merged.items() if k != "_id"}})
            updated_vocabs += 1

    existing_hashes: set[str] = set()
    existing_logs = await db.review_logs.find({}, {"vocabId": 1, "createdAt": 1, "grade": 1, "mode": 1, "questionType": 1}).to_list(length=None)
    for log in existing_logs:
        existing_hashes.add(_log_dedup_hash(log))

    logs_to_insert: list[dict[str, Any]] = []
    incoming_logs = payload.get("review_logs", []) or []
    incoming_logs.sort(key=lambda doc: str(doc.get("createdAt") or ""))

    for incoming_log in incoming_logs:
        source_vocab_id = str(incoming_log.get("vocabId") or "")
        local_vocab_id = source_vocab_to_local.get(source_vocab_id)

        if local_vocab_id is None and ObjectId.is_valid(source_vocab_id):
            candidate = ObjectId(source_vocab_id)
            exists = await db.vocabs.find_one({"_id": candidate}, {"_id": 1})
            if exists:
                local_vocab_id = candidate

        if local_vocab_id is None:
            continue

        normalized_log = {
            "vocabId": local_vocab_id,
            "mode": str(incoming_log.get("mode") or "flip"),
            "questionType": str(incoming_log.get("questionType") or "term_to_meaning"),
            "grade": int(incoming_log.get("grade", 0)),
            "userAnswer": incoming_log.get("userAnswer"),
            "isNearCorrect": incoming_log.get("isNearCorrect"),
            "createdAt": _parse_datetime(incoming_log.get("createdAt"), now),
        }

        dedup_key = _log_dedup_hash(normalized_log)
        if dedup_key in existing_hashes:
            continue

        existing_hashes.add(dedup_key)
        logs_to_insert.append(normalized_log)

    if logs_to_insert:
        result = await db.review_logs.insert_many(logs_to_insert)
        added_logs = len(result.inserted_ids)

    incoming_events = payload.get("events", []) or []
    event_docs: list[dict[str, Any]] = []
    for incoming_event in incoming_events:
        event_docs.append(
            {
                "type": str(incoming_event.get("type") or "IMPORT"),
                "payload": incoming_event.get("payload") or {},
                "createdAt": _parse_datetime(incoming_event.get("createdAt"), now),
            }
        )

    if event_docs:
        await db.events.insert_many(event_docs)

    report = {
        "addedVocabs": added_vocabs,
        "updatedVocabs": updated_vocabs,
        "addedLogs": added_logs,
        "conflicts": conflicts,
    }

    await db.events.insert_one(
        {
            "type": "IMPORT",
            "payload": {
                **report,
                "sourceSchemaVersion": payload.get("schemaVersion", "v1"),
            },
            "createdAt": now,
        }
    )

    return report
