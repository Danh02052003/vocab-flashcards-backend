from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["flip", "mcq", "typing"]
QuestionType = Literal["term_to_meaning", "meaning_to_term"]


class ReviewCreate(BaseModel):
    vocabId: str
    mode: Mode
    questionType: QuestionType = "term_to_meaning"
    grade: int = Field(ge=0, le=5)
    userAnswer: str | None = None


class ReviewResponse(BaseModel):
    vocab: dict
    nextDueAt: datetime
    intervalDays: int
    easeFactor: float
    repetitions: int
    lapses: int


class ReviewLogOut(BaseModel):
    id: str
    vocabId: str
    mode: Mode
    questionType: QuestionType
    grade: int
    userAnswer: str | None
    isNearCorrect: bool | None
    createdAt: datetime
