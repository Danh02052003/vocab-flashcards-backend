import hashlib
import json
from datetime import datetime
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Value is not JSON serializable: {type(value).__name__}")


def stable_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), default=_json_default, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
