from difflib import SequenceMatcher

from app.utils.normalize import normalize_term

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None


def is_near_correct(user_answer: str, candidates: list[str], threshold: int = 85) -> bool:
    answer_norm = normalize_term(user_answer)
    if not answer_norm:
        return False

    candidate_norms = [normalize_term(item) for item in candidates if normalize_term(item)]
    if not candidate_norms:
        return False

    if answer_norm in candidate_norms:
        return True

    if fuzz is not None:
        score = max(
            max(fuzz.ratio(answer_norm, candidate), fuzz.partial_ratio(answer_norm, candidate))
            for candidate in candidate_norms
        )
        return score >= threshold

    ratio = max(SequenceMatcher(None, answer_norm, candidate).ratio() for candidate in candidate_norms)
    return ratio >= threshold / 100
