from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


@dataclass
class Sm2State:
    easeFactor: float = 2.5
    intervalDays: int = 0
    repetitions: int = 0
    lapses: int = 0

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "Sm2State":
        return cls(
            easeFactor=float(doc.get("easeFactor", 2.5)),
            intervalDays=int(doc.get("intervalDays", 0)),
            repetitions=int(doc.get("repetitions", 0)),
            lapses=int(doc.get("lapses", 0)),
        )


def initial_state(now: datetime) -> dict[str, Any]:
    return {
        "easeFactor": 2.5,
        "intervalDays": 0,
        "repetitions": 0,
        "lapses": 0,
        "dueAt": now,
        "lastReviewedAt": None,
    }


def apply_review(state: Sm2State, grade: int, now: datetime) -> dict[str, Any]:
    if grade < 0 or grade > 5:
        raise ValueError("SM-2 grade must be in range 0..5")

    ease = state.easeFactor
    interval = state.intervalDays
    repetitions = state.repetitions
    lapses = state.lapses

    if grade < 3:
        repetitions = 0
        interval = 0
        lapses += 1
        ease = clamp(ease - 0.2, 1.3, 3.0)
        due_at = now
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ease))

        repetitions += 1
        delta = 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)
        ease = clamp(ease + delta, 1.3, 3.0)
        due_at = now + timedelta(days=interval)

    return {
        "easeFactor": round(ease, 2),
        "intervalDays": int(interval),
        "repetitions": int(repetitions),
        "lapses": int(lapses),
        "dueAt": due_at,
        "lastReviewedAt": now,
    }


def apply_readd_penalty(state: Sm2State, now: datetime) -> dict[str, Any]:
    return {
        "easeFactor": round(clamp(state.easeFactor - 0.2, 1.3, 3.0), 2),
        "repetitions": 0,
        "intervalDays": 0,
        "dueAt": now,
    }
