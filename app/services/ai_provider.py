import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from app.config import get_settings


@dataclass(frozen=True)
class EnrichMissing:
    need_examples: bool = False
    need_mnemonics: bool = False
    need_meaning_variants: bool = False
    need_ipa: bool = False

    def any(self) -> bool:
        return self.need_examples or self.need_mnemonics or self.need_meaning_variants or self.need_ipa


class BaseAiProvider:
    provider_name = "stub"

    async def enrich(self, *, term: str, meanings: list[str], missing: EnrichMissing) -> dict[str, Any]:
        raise NotImplementedError

    async def judge_equivalence(self, *, term: str, user_answer: str, meanings: list[str]) -> dict[str, Any]:
        raise NotImplementedError

    async def validate_entry(self, *, term: str, meanings: list[str]) -> dict[str, Any]:
        raise NotImplementedError

    async def speaking_feedback(
        self,
        *,
        prompt: str,
        response_text: str,
        target_words: list[str],
    ) -> dict[str, Any]:
        raise NotImplementedError


class StubAiProvider(BaseAiProvider):
    provider_name = "stub"

    async def enrich(self, *, term: str, meanings: list[str], missing: EnrichMissing) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if missing.need_examples:
            data["examples"] = [
                {
                    "en": f"I used '{term}' in a sentence today.",
                    "vi": f"Hom nay toi da dung tu '{term}' trong mot cau.",
                }
            ]
        if missing.need_mnemonics:
            data["mnemonics"] = [f"Think of '{term}' as a keyword tied to a memorable scene."]
        if missing.need_meaning_variants:
            seed = meanings[0] if meanings else term
            data["meaningVariants"] = [seed, f"{seed} (alternate)"]
        if missing.need_ipa:
            data["ipa"] = f"/{term.strip().lower()}/" if term.strip() else None
        return data

    async def judge_equivalence(self, *, term: str, user_answer: str, meanings: list[str]) -> dict[str, Any]:
        answer = user_answer.strip().lower()
        equivalent = any(answer and answer in meaning.lower() for meaning in meanings if meaning)
        return {
            "isEquivalent": equivalent,
            "reasonShort": "stub semantic check",
        }

    async def validate_entry(self, *, term: str, meanings: list[str]) -> dict[str, Any]:
        raw_term = str(term or "").strip()
        normalized_term = raw_term.lower()
        has_digits = any(ch.isdigit() for ch in raw_term)
        looks_invalid_term = len(raw_term) < 2 or has_digits
        cleaned_meanings = [str(item).strip() for item in meanings if str(item).strip()]
        looks_invalid_meanings = any(len(item) < 2 for item in cleaned_meanings)

        return {
            "isTermValid": not looks_invalid_term,
            "isMeaningPlausible": not looks_invalid_meanings,
            "suggestedTerm": normalized_term if looks_invalid_term else raw_term,
            "suggestedMeanings": cleaned_meanings,
            "reasonShort": "stub lexical check",
        }

    async def speaking_feedback(
        self,
        *,
        prompt: str,
        response_text: str,
        target_words: list[str],
    ) -> dict[str, Any]:
        words = [w for w in response_text.strip().split() if w]
        unique_ratio = len(set(w.lower() for w in words)) / max(len(words), 1)
        lexical_score = round(min(9.0, max(3.0, 4.5 + unique_ratio * 4.0)), 1)
        normalized_response = response_text.lower()
        used_targets = [w for w in target_words if w.lower() in normalized_response]

        return {
            "estimatedBand": lexical_score,
            "targetCoverage": round(len(used_targets) / max(len(target_words), 1), 2) if target_words else 0.0,
            "usedTargetWords": used_targets,
            "strengths": ["clear response"] if words else [],
            "improvements": [
                "use more precise IELTS topic vocabulary",
                "add one collocation and one complex sentence",
            ],
            "reasonShort": "stub speaking feedback",
        }


class OpenAiProvider(BaseAiProvider):
    provider_name = "openai"
    _endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def enrich(self, *, term: str, meanings: list[str], missing: EnrichMissing) -> dict[str, Any]:
        prompt = (
            "Return JSON only. Do not include markdown. "
            f"term={term}; meanings={meanings}; "
            f"need_examples={missing.need_examples}; need_mnemonics={missing.need_mnemonics}; "
            f"need_meaning_variants={missing.need_meaning_variants}; need_ipa={missing.need_ipa}. "
            "Allowed keys: examples, mnemonics, meaningVariants, ipa. "
            "examples is array of {en,vi}; mnemonics is array of strings; meaningVariants is array of strings; ipa is string."
        )
        payload = {
            "model": "gpt-4.1-mini",
            "input": prompt,
            "temperature": 0,
            "max_output_tokens": 220,
        }
        response_data = await self._call_responses_api(payload)
        parsed = _extract_json_dict(response_data)

        result: dict[str, Any] = {}
        if missing.need_examples:
            result["examples"] = _normalize_examples(parsed.get("examples"), term)
        if missing.need_mnemonics:
            result["mnemonics"] = _normalize_strings(parsed.get("mnemonics"))
        if missing.need_meaning_variants:
            result["meaningVariants"] = _normalize_strings(parsed.get("meaningVariants"))
        if missing.need_ipa:
            result["ipa"] = _normalize_ipa(parsed.get("ipa"))
        return result

    async def judge_equivalence(self, *, term: str, user_answer: str, meanings: list[str]) -> dict[str, Any]:
        prompt = (
            "Return JSON only in format {isEquivalent:boolean, reasonShort:string}. "
            f"term={term}; userAnswer={user_answer}; referenceMeanings={meanings}."
        )
        payload = {
            "model": "gpt-4.1-mini",
            "input": prompt,
            "temperature": 0,
            "max_output_tokens": 120,
        }
        response_data = await self._call_responses_api(payload)
        parsed = _extract_json_dict(response_data)
        return {
            "isEquivalent": bool(parsed.get("isEquivalent", False)),
            "reasonShort": str(parsed.get("reasonShort") or "openai semantic check"),
        }

    async def validate_entry(self, *, term: str, meanings: list[str]) -> dict[str, Any]:
        prompt = (
            "Return JSON only in this exact format: "
            "{isTermValid:boolean,isMeaningPlausible:boolean,suggestedTerm:string,suggestedMeanings:string[],reasonShort:string}. "
            f"Input term={term}; meanings={meanings}. "
            "Check if term spelling looks valid English and meanings are plausible for this term."
        )
        payload = {
            "model": "gpt-4.1-mini",
            "input": prompt,
            "temperature": 0,
            "max_output_tokens": 180,
        }
        response_data = await self._call_responses_api(payload)
        parsed = _extract_json_dict(response_data)
        return {
            "isTermValid": bool(parsed.get("isTermValid", True)),
            "isMeaningPlausible": bool(parsed.get("isMeaningPlausible", True)),
            "suggestedTerm": str(parsed.get("suggestedTerm") or term).strip(),
            "suggestedMeanings": _normalize_strings(parsed.get("suggestedMeanings")),
            "reasonShort": str(parsed.get("reasonShort") or "openai vocab validation"),
        }

    async def speaking_feedback(
        self,
        *,
        prompt: str,
        response_text: str,
        target_words: list[str],
    ) -> dict[str, Any]:
        format_hint = (
            "{estimatedBand:number,targetCoverage:number,usedTargetWords:string[],"
            "strengths:string[],improvements:string[],reasonShort:string}"
        )
        input_prompt = (
            "Return JSON only. "
            f"Format={format_hint}. "
            f"IELTS speaking prompt={prompt}; userResponse={response_text}; targetWords={target_words}. "
            "Score lexical resource only."
        )
        payload = {
            "model": "gpt-4.1-mini",
            "input": input_prompt,
            "temperature": 0,
            "max_output_tokens": 220,
        }
        response_data = await self._call_responses_api(payload)
        parsed = _extract_json_dict(response_data)
        estimated_band_raw = parsed.get("estimatedBand", 5.0)
        try:
            estimated_band = float(estimated_band_raw)
        except Exception:
            estimated_band = 5.0
        return {
            "estimatedBand": min(9.0, max(1.0, round(estimated_band, 1))),
            "targetCoverage": float(parsed.get("targetCoverage", 0.0)),
            "usedTargetWords": _normalize_strings(parsed.get("usedTargetWords")),
            "strengths": _normalize_strings(parsed.get("strengths")),
            "improvements": _normalize_strings(parsed.get("improvements")),
            "reasonShort": str(parsed.get("reasonShort") or "openai speaking feedback"),
        }

    async def _call_responses_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _sync_call() -> dict[str, Any]:
            req = request.Request(
                self._endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)

        try:
            return await asyncio.to_thread(_sync_call)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI API HTTPError: {exc.code} {body}") from exc
        except Exception as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc


def _normalize_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalize_examples(value: Any, term: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    examples: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        en = str(item.get("en") or "").strip()
        vi = str(item.get("vi") or "").strip()
        if en and vi:
            examples.append({"en": en, "vi": vi})

    if examples:
        return examples

    return [{"en": f"I used '{term}' in a sentence today.", "vi": f"Hom nay toi da dung tu '{term}'."}]


def _normalize_ipa(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _extract_json_dict(response_data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(response_data.get("output_text"), str) and response_data["output_text"].strip():
        return _parse_json_object(response_data["output_text"])

    text_parts: list[str] = []
    for block in response_data.get("output", []):
        for content in block.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text)

    if not text_parts:
        return {}

    return _parse_json_object("\n".join(text_parts))


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    candidate = raw_text.strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start >= 0 and end > start:
        candidate = candidate[start : end + 1]

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def get_ai_provider() -> BaseAiProvider:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAiProvider(settings.openai_api_key)
    return StubAiProvider()
