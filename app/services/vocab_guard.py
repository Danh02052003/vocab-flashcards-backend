from typing import Any

from app.services.ai_cache import CACHE_VERSION, get_cache, upsert_cache
from app.services.ai_provider import StubAiProvider, get_ai_provider
from app.utils.hash import stable_hash
from app.utils.normalize import normalize_term
from app.utils.time import now_local


def _normalize_meanings(meanings: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in meanings or []:
        text = str(item).strip()
        if not text:
            continue
        key = normalize_term(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _cache_key(term_normalized: str, term: str, meanings: list[str]) -> str:
    payload = {
        "term": term.strip(),
        "meanings": sorted(normalize_term(item) for item in meanings),
    }
    return f"validate:{CACHE_VERSION}:{term_normalized}:{stable_hash(payload)}"


async def validate_typed_vocab_input(
    *,
    term: str,
    meanings: list[str],
    input_method: str,
) -> dict[str, Any]:
    if input_method != "typed":
        return {
            "checked": False,
            "accepted": True,
            "provider": "skipped",
            "fromCache": False,
            "result": {},
        }

    term_clean = str(term or "").strip()
    term_normalized = normalize_term(term_clean)
    meanings_clean = _normalize_meanings(meanings)

    if not term_normalized:
        return {
            "checked": True,
            "accepted": False,
            "provider": "local",
            "fromCache": False,
            "result": {
                "isTermValid": False,
                "isMeaningPlausible": True,
                "suggestedTerm": "",
                "suggestedMeanings": meanings_clean,
                "reasonShort": "Empty term after normalization",
            },
        }

    key = _cache_key(term_normalized, term_clean, meanings_clean)
    cached = await get_cache(key)
    if cached and isinstance(cached.get("data"), dict) and isinstance(cached["data"].get("validate"), dict):
        result = cached["data"]["validate"]
        accepted = bool(result.get("isTermValid", True)) and bool(result.get("isMeaningPlausible", True))
        return {
            "checked": True,
            "accepted": accepted,
            "provider": str(cached.get("provider", "stub")),
            "fromCache": True,
            "result": result,
        }

    provider = get_ai_provider()
    provider_name = provider.provider_name
    try:
        result = await provider.validate_entry(term=term_clean, meanings=meanings_clean)
    except Exception:
        fallback = StubAiProvider()
        result = await fallback.validate_entry(term=term_clean, meanings=meanings_clean)
        provider_name = fallback.provider_name

    if not isinstance(result, dict):
        result = {
            "isTermValid": True,
            "isMeaningPlausible": True,
            "suggestedTerm": term_clean,
            "suggestedMeanings": meanings_clean,
            "reasonShort": "fallback accepted",
        }

    await upsert_cache(
        key=key,
        term_normalized=term_normalized,
        provider=provider_name,
        data={"validate": result},
        now=now_local(),
    )

    accepted = bool(result.get("isTermValid", True)) and bool(result.get("isMeaningPlausible", True))
    return {
        "checked": True,
        "accepted": accepted,
        "provider": provider_name,
        "fromCache": False,
        "result": result,
    }
