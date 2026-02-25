import re


_SURROUNDING_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_term(term: str) -> str:
    normalized = _MULTI_SPACE.sub(" ", (term or "").strip().lower())
    normalized = _SURROUNDING_PUNCT.sub("", normalized)
    return _MULTI_SPACE.sub(" ", normalized).strip()
