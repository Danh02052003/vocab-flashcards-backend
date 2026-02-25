import re
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.models.vocab import (
    VocabCreate,
    VocabOut,
    VocabUpdate,
    VocabUpsertWithAiOut,
    VocabUpsertWithAiRequest,
    vocab_doc_to_out,
)
from app.services.ai_cache import CACHE_VERSION, get_cache, merge_ai_data, upsert_cache
from app.services.ai_provider import EnrichMissing, StubAiProvider, get_ai_provider
from app.services.srs_sm2 import Sm2State, apply_readd_penalty, initial_state
from app.services.vocab_guard import validate_typed_vocab_input
from app.utils.normalize import normalize_term
from app.utils.time import now_local

router = APIRouter(prefix="/vocab", tags=["vocab"])

MIN_EXAMPLES = 1
MIN_MNEMONICS = 1
TARGET_MEANINGS = 2


def _parse_object_id(raw: str) -> ObjectId:
    if not ObjectId.is_valid(raw):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")
    return ObjectId(raw)


def _unique_strings(items: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _merge_unique_strings(left: list[str] | None, right: list[str] | None) -> list[str]:
    return _unique_strings((left or []) + (right or []))


def _normalize_word_family(data: dict[str, list[str]] | None) -> dict[str, list[str]]:
    if not isinstance(data, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for key, values in data.items():
        role = str(key).strip().lower()
        if not role:
            continue
        normalized[role] = _unique_strings(values)
    return normalized


def _merge_word_family(left: dict[str, list[str]] | None, right: dict[str, list[str]] | None) -> dict[str, list[str]]:
    result = _normalize_word_family(left)
    right_norm = _normalize_word_family(right)
    for role, values in right_norm.items():
        result[role] = _merge_unique_strings(result.get(role, []), values)
    return result


def _extract_examples(vocab_doc: dict[str, Any] | None, cache_data: dict[str, Any]) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    cached_examples = cache_data.get("examples") if isinstance(cache_data, dict) else []
    if isinstance(cached_examples, list):
        for item in cached_examples:
            if not isinstance(item, dict):
                continue
            en = str(item.get("en") or "").strip()
            vi = str(item.get("vi") or "").strip()
            if en and vi:
                examples.append({"en": en, "vi": vi})

    if vocab_doc:
        en = str(vocab_doc.get("exampleEn") or "").strip()
        vi = str(vocab_doc.get("exampleVi") or "").strip()
        if en and vi and not any(ex["en"] == en and ex["vi"] == vi for ex in examples):
            examples.insert(0, {"en": en, "vi": vi})

    return examples


def _build_suggestions(vocab_doc: dict[str, Any] | None, cache_data: dict[str, Any]) -> dict[str, Any]:
    cache_mnemonics = (cache_data.get("mnemonics") or []) if isinstance(cache_data, dict) else []
    cache_meaning_variants = (cache_data.get("meaningVariants") or []) if isinstance(cache_data, dict) else []
    cache_synonym_groups = (cache_data.get("synonymGroups") or []) if isinstance(cache_data, dict) else []
    cache_distractors = (cache_data.get("distractors") or []) if isinstance(cache_data, dict) else []

    mnemonics = _unique_strings(
        cache_mnemonics
        + ([vocab_doc.get("mnemonic")] if vocab_doc and vocab_doc.get("mnemonic") else [])
    )
    return {
        "examples": _extract_examples(vocab_doc, cache_data),
        "mnemonics": mnemonics,
        "meaningVariants": _unique_strings(cache_meaning_variants),
        "ipa": (
            str(vocab_doc.get("ipa") or "").strip()
            if vocab_doc and str(vocab_doc.get("ipa") or "").strip()
            else str(cache_data.get("ipa") or "").strip() or None
        ),
        "synonymGroups": cache_synonym_groups,
        "distractors": cache_distractors,
    }


@router.post("", response_model=VocabOut)
async def create_vocab(payload: VocabCreate):
    db = get_db()
    now = now_local()
    term_normalized = normalize_term(payload.term)
    if not term_normalized:
        raise HTTPException(status_code=422, detail="Term is empty after normalization")

    validation = await validate_typed_vocab_input(
        term=payload.term,
        meanings=payload.meanings,
        input_method=payload.inputMethod,
    )
    if not validation["accepted"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Input looks incorrect. Please review spelling/meaning before saving.",
                "validation": validation,
            },
        )

    create_doc: dict[str, Any] = {
        "term": payload.term.strip(),
        "termNormalized": term_normalized,
        "meanings": _unique_strings(payload.meanings),
        "ipa": str(payload.ipa).strip() if payload.ipa else None,
        "exampleEn": payload.exampleEn,
        "exampleVi": payload.exampleVi,
        "mnemonic": payload.mnemonic,
        "tags": _unique_strings(payload.tags),
        "collocations": _unique_strings(payload.collocations),
        "phrases": _unique_strings(payload.phrases),
        "wordFamily": _normalize_word_family(payload.wordFamily),
        "topics": _unique_strings(payload.topics),
        "cefrLevel": payload.cefrLevel,
        "ieltsBand": payload.ieltsBand,
        "createdAt": now,
        "updatedAt": now,
        "readdCount": 0,
        "lastReaddAt": None,
        **initial_state(now),
    }

    try:
        result = await db.vocabs.insert_one(create_doc)
        doc = await db.vocabs.find_one({"_id": result.inserted_id})
        return vocab_doc_to_out(doc)
    except DuplicateKeyError:
        existing = await db.vocabs.find_one({"termNormalized": term_normalized})
        if not existing:
            raise HTTPException(status_code=409, detail="Duplicate term conflict")

        penalty = apply_readd_penalty(Sm2State.from_doc(existing), now=now)
        merged_meanings = _merge_unique_strings(existing.get("meanings", []), payload.meanings)
        merged_collocations = _merge_unique_strings(existing.get("collocations", []), payload.collocations)
        merged_phrases = _merge_unique_strings(existing.get("phrases", []), payload.phrases)
        merged_topics = _merge_unique_strings(existing.get("topics", []), payload.topics)
        merged_word_family = _merge_word_family(existing.get("wordFamily", {}), payload.wordFamily)

        await db.vocabs.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "meanings": merged_meanings,
                    "collocations": merged_collocations,
                    "phrases": merged_phrases,
                    "topics": merged_topics,
                    "wordFamily": merged_word_family,
                    "cefrLevel": payload.cefrLevel or existing.get("cefrLevel"),
                    "ieltsBand": payload.ieltsBand if payload.ieltsBand is not None else existing.get("ieltsBand"),
                    "ipa": (
                        str(payload.ipa).strip()
                        if payload.ipa is not None and str(payload.ipa).strip()
                        else existing.get("ipa")
                    ),
                    "updatedAt": now,
                    "lastReaddAt": now,
                    **penalty,
                },
                "$inc": {"readdCount": 1},
            },
        )

        await db.events.insert_one(
            {
                "type": "RE_ADD",
                "payload": {
                    "vocabId": str(existing["_id"]),
                    "termNormalized": term_normalized,
                },
                "createdAt": now,
            }
        )

        updated = await db.vocabs.find_one({"_id": existing["_id"]})
        return vocab_doc_to_out(updated)


@router.post("/upsert_with_ai", response_model=VocabUpsertWithAiOut)
async def upsert_vocab_with_ai(payload: VocabUpsertWithAiRequest):
    db = get_db()
    now = now_local()

    term = payload.term.strip()
    term_normalized = normalize_term(term)
    if not term_normalized:
        raise HTTPException(status_code=422, detail="Term is empty after normalization")

    validation = await validate_typed_vocab_input(
        term=payload.term,
        meanings=payload.meanings,
        input_method=payload.inputMethod,
    )
    if not validation["accepted"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Input looks incorrect. Please review spelling/meaning before saving.",
                "validation": validation,
            },
        )

    incoming_meanings = _unique_strings(payload.meanings)
    incoming_tags = _unique_strings(payload.tags)
    incoming_ipa = str(payload.ipa).strip() if payload.ipa else None
    incoming_collocations = _unique_strings(payload.collocations)
    incoming_phrases = _unique_strings(payload.phrases)
    incoming_topics = _unique_strings(payload.topics)
    incoming_word_family = _normalize_word_family(payload.wordFamily)

    existing = await db.vocabs.find_one({"termNormalized": term_normalized})
    overwritten = False

    if not existing:
        create_doc: dict[str, Any] = {
            "term": term,
            "termNormalized": term_normalized,
            "meanings": incoming_meanings,
            "ipa": incoming_ipa,
            "exampleEn": payload.exampleEn,
            "exampleVi": payload.exampleVi,
            "mnemonic": payload.mnemonic,
            "tags": incoming_tags,
            "collocations": incoming_collocations,
            "phrases": incoming_phrases,
            "topics": incoming_topics,
            "wordFamily": incoming_word_family,
            "cefrLevel": payload.cefrLevel,
            "ieltsBand": payload.ieltsBand,
            "createdAt": now,
            "updatedAt": now,
            "readdCount": 0,
            "lastReaddAt": None,
            **initial_state(now),
        }
        result = await db.vocabs.insert_one(create_doc)
        vocab_doc = await db.vocabs.find_one({"_id": result.inserted_id})
        action = "created"
    else:
        update_doc: dict[str, Any] = {"updatedAt": now, "term": term}
        existing_meanings = _unique_strings(existing.get("meanings", []))
        existing_tags = _unique_strings(existing.get("tags", []))
        existing_collocations = _unique_strings(existing.get("collocations", []))
        existing_phrases = _unique_strings(existing.get("phrases", []))
        existing_topics = _unique_strings(existing.get("topics", []))
        existing_word_family = _normalize_word_family(existing.get("wordFamily", {}))
        has_changes = term != str(existing.get("term", ""))

        if payload.overwriteExisting:
            if incoming_meanings and incoming_meanings != existing_meanings:
                update_doc["meanings"] = incoming_meanings
                overwritten = True
                has_changes = True
            if incoming_tags and incoming_tags != existing_tags:
                update_doc["tags"] = incoming_tags
                overwritten = True
                has_changes = True
            if incoming_collocations and incoming_collocations != existing_collocations:
                update_doc["collocations"] = incoming_collocations
                overwritten = True
                has_changes = True
            if incoming_phrases and incoming_phrases != existing_phrases:
                update_doc["phrases"] = incoming_phrases
                overwritten = True
                has_changes = True
            if incoming_topics and incoming_topics != existing_topics:
                update_doc["topics"] = incoming_topics
                overwritten = True
                has_changes = True
            if incoming_word_family and incoming_word_family != existing_word_family:
                update_doc["wordFamily"] = incoming_word_family
                overwritten = True
                has_changes = True
            if payload.cefrLevel is not None and payload.cefrLevel != existing.get("cefrLevel"):
                update_doc["cefrLevel"] = payload.cefrLevel
                overwritten = True
                has_changes = True
            if payload.ieltsBand is not None and payload.ieltsBand != existing.get("ieltsBand"):
                update_doc["ieltsBand"] = payload.ieltsBand
                overwritten = True
                has_changes = True
            if payload.ipa is not None and str(payload.ipa).strip() != str(existing.get("ipa") or "").strip():
                update_doc["ipa"] = incoming_ipa
                overwritten = True
                has_changes = True
            if payload.exampleEn is not None and payload.exampleEn != existing.get("exampleEn"):
                update_doc["exampleEn"] = payload.exampleEn
                overwritten = True
                has_changes = True
            if payload.exampleVi is not None and payload.exampleVi != existing.get("exampleVi"):
                update_doc["exampleVi"] = payload.exampleVi
                overwritten = True
                has_changes = True
            if payload.mnemonic is not None and payload.mnemonic != existing.get("mnemonic"):
                update_doc["mnemonic"] = payload.mnemonic
                overwritten = True
                has_changes = True
        else:
            if incoming_meanings:
                merged_meanings = _merge_unique_strings(existing_meanings, incoming_meanings)
                if merged_meanings != existing_meanings:
                    update_doc["meanings"] = merged_meanings
                    has_changes = True
            if incoming_tags:
                merged_tags = _merge_unique_strings(existing_tags, incoming_tags)
                if merged_tags != existing_tags:
                    update_doc["tags"] = merged_tags
                    has_changes = True
            if incoming_collocations:
                merged_collocations = _merge_unique_strings(existing_collocations, incoming_collocations)
                if merged_collocations != existing_collocations:
                    update_doc["collocations"] = merged_collocations
                    has_changes = True
            if incoming_phrases:
                merged_phrases = _merge_unique_strings(existing_phrases, incoming_phrases)
                if merged_phrases != existing_phrases:
                    update_doc["phrases"] = merged_phrases
                    has_changes = True
            if incoming_topics:
                merged_topics = _merge_unique_strings(existing_topics, incoming_topics)
                if merged_topics != existing_topics:
                    update_doc["topics"] = merged_topics
                    has_changes = True
            if incoming_word_family:
                merged_word_family = _merge_word_family(existing_word_family, incoming_word_family)
                if merged_word_family != existing_word_family:
                    update_doc["wordFamily"] = merged_word_family
                    has_changes = True
            if payload.cefrLevel and not existing.get("cefrLevel"):
                update_doc["cefrLevel"] = payload.cefrLevel
                has_changes = True
            if payload.ieltsBand is not None and existing.get("ieltsBand") is None:
                update_doc["ieltsBand"] = payload.ieltsBand
                has_changes = True
            if incoming_ipa and not str(existing.get("ipa") or "").strip():
                update_doc["ipa"] = incoming_ipa
                has_changes = True
            if payload.exampleEn and not existing.get("exampleEn"):
                update_doc["exampleEn"] = payload.exampleEn
                has_changes = True
            if payload.exampleVi and not existing.get("exampleVi"):
                update_doc["exampleVi"] = payload.exampleVi
                has_changes = True
            if payload.mnemonic and not existing.get("mnemonic"):
                update_doc["mnemonic"] = payload.mnemonic
                has_changes = True

        if has_changes:
            await db.vocabs.update_one({"_id": existing["_id"]}, {"$set": update_doc})
        vocab_doc = await db.vocabs.find_one({"_id": existing["_id"]})
        action = "updated"

    ai_info = {"enabled": payload.useAi, "provider": None, "aiCalled": False, "fromCache": False}
    suggestions: dict[str, Any] = {
        "examples": [],
        "mnemonics": [],
        "meaningVariants": [],
        "ipa": None,
        "synonymGroups": [],
        "distractors": [],
    }

    if payload.useAi:
        cache_key = f"enrich:{CACHE_VERSION}:{term_normalized}"
        cache_doc = await get_cache(cache_key)
        cache_data = (cache_doc or {}).get("data") or {}

        vocab_meanings = _unique_strings(vocab_doc.get("meanings", []))
        suggestions_before = _build_suggestions(vocab_doc, cache_data)
        has_core = (
            len(vocab_meanings) >= TARGET_MEANINGS
            and bool(str(vocab_doc.get("exampleEn") or "").strip())
            and bool(str(vocab_doc.get("mnemonic") or "").strip())
        )
        missing = EnrichMissing(
            need_examples=payload.forceAi or ((not has_core) and len(suggestions_before["examples"]) < MIN_EXAMPLES),
            need_mnemonics=payload.forceAi or ((not has_core) and len(suggestions_before["mnemonics"]) < MIN_MNEMONICS),
            need_meaning_variants=payload.forceAi or ((not has_core) and len(vocab_meanings) < TARGET_MEANINGS),
            need_ipa=payload.forceAi or (not str(vocab_doc.get("ipa") or "").strip() and not str(cache_data.get("ipa") or "").strip()),
        )

        provider_used = cache_doc.get("provider") if cache_doc else "stub"
        generated: dict[str, Any] = {}

        if missing.any():
            ai_info["aiCalled"] = True
            provider = get_ai_provider()
            provider_used = provider.provider_name
            try:
                generated = await provider.enrich(term=vocab_doc["term"], meanings=vocab_meanings, missing=missing)
                # OpenAI can return empty content; fallback to stub to ensure actionable suggestions.
                if not generated:
                    fallback = StubAiProvider()
                    generated = await fallback.enrich(term=vocab_doc["term"], meanings=vocab_meanings, missing=missing)
                    provider_used = fallback.provider_name
            except Exception:
                fallback = StubAiProvider()
                generated = await fallback.enrich(term=vocab_doc["term"], meanings=vocab_meanings, missing=missing)
                provider_used = fallback.provider_name

        merged_cache_data = merge_ai_data(cache_data, generated)
        if not cache_doc or generated or payload.forceAi:
            cache_doc = await upsert_cache(
                key=cache_key,
                term_normalized=term_normalized,
                provider=provider_used,
                data=merged_cache_data,
                now=now,
            )
            merged_cache_data = cache_doc.get("data", merged_cache_data)

        ai_update_doc: dict[str, Any] = {}
        merged_examples = _extract_examples(vocab_doc, merged_cache_data)
        if not str(vocab_doc.get("exampleEn") or "").strip() and merged_examples:
            ai_update_doc["exampleEn"] = merged_examples[0]["en"]
        if not str(vocab_doc.get("exampleVi") or "").strip() and merged_examples:
            ai_update_doc["exampleVi"] = merged_examples[0]["vi"]

        merged_mnemonics = _unique_strings(
            (merged_cache_data.get("mnemonics") or [])
            + ([vocab_doc.get("mnemonic")] if vocab_doc.get("mnemonic") else [])
        )
        if not str(vocab_doc.get("mnemonic") or "").strip() and merged_mnemonics:
            ai_update_doc["mnemonic"] = merged_mnemonics[0]

        if len(vocab_meanings) < TARGET_MEANINGS:
            enriched_meanings = _merge_unique_strings(vocab_meanings, merged_cache_data.get("meaningVariants") or [])
            if enriched_meanings != vocab_meanings:
                ai_update_doc["meanings"] = enriched_meanings
        if not str(vocab_doc.get("ipa") or "").strip() and str(merged_cache_data.get("ipa") or "").strip():
            ai_update_doc["ipa"] = str(merged_cache_data.get("ipa")).strip()

        if ai_update_doc:
            ai_update_doc["updatedAt"] = now
            await db.vocabs.update_one({"_id": vocab_doc["_id"]}, {"$set": ai_update_doc})
            vocab_doc = await db.vocabs.find_one({"_id": vocab_doc["_id"]})

        suggestions = _build_suggestions(vocab_doc, merged_cache_data)
        ai_info["provider"] = provider_used
        ai_info["fromCache"] = bool(cache_doc) and not ai_info["aiCalled"]
    else:
        suggestions = _build_suggestions(vocab_doc, {})

    return VocabUpsertWithAiOut(
        action=action,
        overwritten=overwritten,
        vocab=vocab_doc_to_out(vocab_doc),
        ai=ai_info,
        suggestions=suggestions,
    )


@router.get("", response_model=list[VocabOut])
async def list_vocab(
    search: str | None = None,
    tag: str | None = None,
    topic: str | None = None,
    cefrLevel: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
):
    db = get_db()
    query: dict[str, Any] = {}

    if search:
        pattern = re.escape(search.strip())
        if pattern:
            query["$or"] = [
                {"term": {"$regex": pattern, "$options": "i"}},
                {"meanings": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                {"tags": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                {"collocations": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                {"phrases": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                {"topics": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
            ]

    if tag:
        query["tags"] = tag.strip()
    if topic:
        query["topics"] = topic.strip()
    if cefrLevel:
        query["cefrLevel"] = cefrLevel.strip().upper()

    skip = (page - 1) * limit
    docs = await db.vocabs.find(query).sort("updatedAt", -1).skip(skip).limit(limit).to_list(length=limit)
    return [vocab_doc_to_out(doc) for doc in docs]


@router.get("/{vocab_id}", response_model=VocabOut)
async def get_vocab(vocab_id: str):
    db = get_db()
    oid = _parse_object_id(vocab_id)
    doc = await db.vocabs.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Vocab not found")
    return vocab_doc_to_out(doc)


@router.put("/{vocab_id}", response_model=VocabOut)
async def update_vocab(vocab_id: str, payload: VocabUpdate):
    db = get_db()
    oid = _parse_object_id(vocab_id)
    existing = await db.vocabs.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Vocab not found")

    update_doc = payload.model_dump(exclude_unset=True)
    if not update_doc:
        return vocab_doc_to_out(existing)

    if "term" in update_doc:
        term_norm = normalize_term(str(update_doc["term"]))
        if not term_norm:
            raise HTTPException(status_code=422, detail="Term is empty after normalization")
        update_doc["termNormalized"] = term_norm
        update_doc["term"] = str(update_doc["term"]).strip()

    if "meanings" in update_doc:
        update_doc["meanings"] = _unique_strings(update_doc.get("meanings") or [])
    if "ipa" in update_doc:
        update_doc["ipa"] = str(update_doc.get("ipa")).strip() or None

    if "tags" in update_doc:
        update_doc["tags"] = _unique_strings(update_doc.get("tags") or [])

    if "collocations" in update_doc:
        update_doc["collocations"] = _unique_strings(update_doc.get("collocations") or [])

    if "phrases" in update_doc:
        update_doc["phrases"] = _unique_strings(update_doc.get("phrases") or [])

    if "topics" in update_doc:
        update_doc["topics"] = _unique_strings(update_doc.get("topics") or [])

    if "wordFamily" in update_doc:
        update_doc["wordFamily"] = _normalize_word_family(update_doc.get("wordFamily") or {})

    update_doc["updatedAt"] = now_local()

    try:
        await db.vocabs.update_one({"_id": oid}, {"$set": update_doc})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Another vocab already uses this term")

    updated = await db.vocabs.find_one({"_id": oid})
    return vocab_doc_to_out(updated)


@router.delete("/{vocab_id}")
async def delete_vocab(vocab_id: str):
    db = get_db()
    oid = _parse_object_id(vocab_id)
    delete_result = await db.vocabs.delete_one({"_id": oid})
    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Vocab not found")

    await db.review_logs.delete_many({"vocabId": oid})
    return {"deleted": True}
