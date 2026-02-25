from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import get_db
from app.models.vocab import vocab_doc_to_out
from app.services.ai_cache import CACHE_VERSION, get_cache, merge_ai_data, upsert_cache
from app.services.ai_provider import EnrichMissing, StubAiProvider, get_ai_provider
from app.services.typing_judge import is_near_correct
from app.utils.hash import stable_hash
from app.utils.normalize import normalize_term
from app.utils.time import now_local

router = APIRouter(prefix="/ai", tags=["ai"])

MIN_EXAMPLES = 1
MIN_MNEMONICS = 1
TARGET_MEANINGS = 2


class EnrichRequest(BaseModel):
    term: str = Field(min_length=1)
    meaningsExisting: list[str] = Field(default_factory=list)


class JudgeRequest(BaseModel):
    term: str = Field(min_length=1)
    userAnswer: str = Field(min_length=1)
    meanings: list[str] = Field(default_factory=list)


def _unique_strings(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


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


async def _learn_equivalent_answer(*, term_normalized: str, user_answer: str, provider: str) -> None:
    raw_answer = str(user_answer or "").strip()
    normalized_answer = normalize_term(raw_answer)
    if not normalized_answer:
        return

    db = get_db()
    now = now_local()

    vocab = await db.vocabs.find_one({"termNormalized": term_normalized})
    if vocab:
        existing_meanings = _unique_strings(vocab.get("meanings", []))
        existing_normalized = {normalize_term(item) for item in existing_meanings}
        if normalized_answer not in existing_normalized:
            await db.vocabs.update_one(
                {"_id": vocab["_id"]},
                {
                    "$set": {
                        "meanings": existing_meanings + [raw_answer],
                        "updatedAt": now,
                    }
                },
            )

    enrich_key = f"enrich:{CACHE_VERSION}:{term_normalized}"
    enrich_cache = await get_cache(enrich_key)
    enrich_data = (enrich_cache or {}).get("data") or {}
    meaning_variants = _unique_strings(enrich_data.get("meaningVariants") or [])
    variant_normalized = {normalize_term(item) for item in meaning_variants}
    if normalized_answer not in variant_normalized:
        merged = dict(enrich_data)
        merged["meaningVariants"] = meaning_variants + [raw_answer]
        await upsert_cache(
            key=enrich_key,
            term_normalized=term_normalized,
            provider=(enrich_cache or {}).get("provider", provider),
            data=merged,
            now=now,
        )


@router.post("/enrich")
async def enrich_vocab(payload: EnrichRequest):
    db = get_db()
    now = now_local()

    term_normalized = normalize_term(payload.term)
    if not term_normalized:
        raise HTTPException(status_code=422, detail="Term is empty after normalization")

    vocab = await db.vocabs.find_one({"termNormalized": term_normalized})

    cache_key = f"enrich:{CACHE_VERSION}:{term_normalized}"
    cache_doc = await get_cache(cache_key)
    cache_data = (cache_doc or {}).get("data") or {}

    vocab_meanings = vocab.get("meanings", []) if vocab else []
    all_meanings = _unique_strings((vocab_meanings or []) + (payload.meaningsExisting or []))

    examples = _extract_examples(vocab, cache_data)
    mnemonics = _unique_strings((cache_data.get("mnemonics") or []) + ([vocab.get("mnemonic")] if vocab and vocab.get("mnemonic") else []))

    has_core_content = (
        len(all_meanings) >= TARGET_MEANINGS
        and bool(vocab and str(vocab.get("exampleEn") or "").strip())
        and bool(vocab and str(vocab.get("mnemonic") or "").strip())
    )

    missing = EnrichMissing(
        need_examples=(not has_core_content) and len(examples) < MIN_EXAMPLES,
        need_mnemonics=(not has_core_content) and len(mnemonics) < MIN_MNEMONICS,
        need_meaning_variants=(not has_core_content) and len(all_meanings) < TARGET_MEANINGS,
        need_ipa=(not str((vocab or {}).get("ipa") or "").strip()) and (not str(cache_data.get("ipa") or "").strip()),
    )

    generated: dict[str, Any] = {}
    provider_used = cache_doc.get("provider") if cache_doc else "stub"
    ai_called = False

    if missing.any():
        ai_called = True
        provider = get_ai_provider()
        provider_used = provider.provider_name
        try:
            generated = await provider.enrich(term=payload.term.strip(), meanings=all_meanings, missing=missing)
        except Exception:
            fallback = StubAiProvider()
            generated = await fallback.enrich(term=payload.term.strip(), meanings=all_meanings, missing=missing)
            provider_used = fallback.provider_name

    merged_data = merge_ai_data(cache_data, generated)

    if not cache_doc or generated:
        cache_doc = await upsert_cache(
            key=cache_key,
            term_normalized=term_normalized,
            provider=provider_used,
            data=merged_data,
            now=now,
        )
        merged_data = cache_doc.get("data", merged_data)

    updated_vocab = vocab
    if vocab:
        update_doc: dict[str, Any] = {}

        merged_examples = _extract_examples(vocab, merged_data)
        if not str(vocab.get("exampleEn") or "").strip() and merged_examples:
            update_doc["exampleEn"] = merged_examples[0]["en"]
        if not str(vocab.get("exampleVi") or "").strip() and merged_examples:
            update_doc["exampleVi"] = merged_examples[0]["vi"]

        merged_mnemonics = _unique_strings((merged_data.get("mnemonics") or []) + ([vocab.get("mnemonic")] if vocab.get("mnemonic") else []))
        if not str(vocab.get("mnemonic") or "").strip() and merged_mnemonics:
            update_doc["mnemonic"] = merged_mnemonics[0]

        if len(vocab_meanings) < TARGET_MEANINGS:
            merged_meanings = _unique_strings((vocab_meanings or []) + (merged_data.get("meaningVariants") or []))
            if merged_meanings != vocab_meanings:
                update_doc["meanings"] = merged_meanings
        if not str(vocab.get("ipa") or "").strip() and str(merged_data.get("ipa") or "").strip():
            update_doc["ipa"] = str(merged_data.get("ipa")).strip()

        if update_doc:
            update_doc["updatedAt"] = now
            await db.vocabs.update_one({"_id": vocab["_id"]}, {"$set": update_doc})
            updated_vocab = await db.vocabs.find_one({"_id": vocab["_id"]})

    response_data = {
        "examples": _extract_examples(updated_vocab or vocab, merged_data),
        "mnemonics": _unique_strings((merged_data.get("mnemonics") or []) + ([updated_vocab.get("mnemonic")] if updated_vocab and updated_vocab.get("mnemonic") else [])),
        "meaningVariants": _unique_strings(merged_data.get("meaningVariants") or []),
        "ipa": (
            str((updated_vocab or vocab or {}).get("ipa") or "").strip()
            if str((updated_vocab or vocab or {}).get("ipa") or "").strip()
            else str(merged_data.get("ipa") or "").strip() or None
        ),
        "synonymGroups": merged_data.get("synonymGroups") or [],
        "distractors": merged_data.get("distractors") or [],
    }

    return {
        "termNormalized": term_normalized,
        "provider": provider_used,
        "aiCalled": ai_called,
        "fromCache": bool(cache_doc) and not ai_called,
        "data": response_data,
        "vocab": vocab_doc_to_out(updated_vocab).model_dump() if updated_vocab else None,
    }


@router.post("/judge_equivalence")
async def judge_equivalence(payload: JudgeRequest):
    term_normalized = normalize_term(payload.term)
    if not term_normalized:
        raise HTTPException(status_code=422, detail="Term is empty after normalization")

    meanings = _unique_strings(payload.meanings)
    hash_input = {
        "userAnswer": normalize_term(payload.userAnswer),
        "meanings": sorted(normalize_term(item) for item in meanings),
    }
    content_hash = stable_hash(hash_input)
    cache_key = f"judge:{CACHE_VERSION}:{term_normalized}:{content_hash}"

    if is_near_correct(payload.userAnswer, meanings):
        judge_data = {"isEquivalent": True, "reasonShort": "fuzzy match"}
        await upsert_cache(
            key=cache_key,
            term_normalized=term_normalized,
            provider="fuzzy",
            data={"judge": judge_data},
            now=now_local(),
        )
        await _learn_equivalent_answer(
            term_normalized=term_normalized,
            user_answer=payload.userAnswer,
            provider="fuzzy",
        )
        return {
            "isEquivalent": True,
            "reasonShort": "fuzzy match",
            "provider": "fuzzy",
            "cached": False,
        }

    cache_doc = await get_cache(cache_key)
    if cache_doc and isinstance(cache_doc.get("data"), dict) and isinstance(cache_doc["data"].get("judge"), dict):
        judge_data = cache_doc["data"]["judge"]
        if bool(judge_data.get("isEquivalent", False)):
            await _learn_equivalent_answer(
                term_normalized=term_normalized,
                user_answer=payload.userAnswer,
                provider=str(cache_doc.get("provider", "stub")),
            )
        return {
            "isEquivalent": bool(judge_data.get("isEquivalent", False)),
            "reasonShort": str(judge_data.get("reasonShort") or "cached"),
            "provider": cache_doc.get("provider", "stub"),
            "cached": True,
        }

    provider = get_ai_provider()
    provider_used = provider.provider_name
    try:
        judge_data = await provider.judge_equivalence(
            term=payload.term.strip(),
            user_answer=payload.userAnswer.strip(),
            meanings=meanings,
        )
    except Exception:
        fallback = StubAiProvider()
        judge_data = await fallback.judge_equivalence(
            term=payload.term.strip(),
            user_answer=payload.userAnswer.strip(),
            meanings=meanings,
        )
        provider_used = fallback.provider_name

    await upsert_cache(
        key=cache_key,
        term_normalized=term_normalized,
        provider=provider_used,
        data={"judge": judge_data},
        now=now_local(),
    )

    if bool(judge_data.get("isEquivalent", False)):
        await _learn_equivalent_answer(
            term_normalized=term_normalized,
            user_answer=payload.userAnswer,
            provider=provider_used,
        )

    return {
        "isEquivalent": bool(judge_data.get("isEquivalent", False)),
        "reasonShort": str(judge_data.get("reasonShort") or "ai semantic check"),
        "provider": provider_used,
        "cached": False,
    }
