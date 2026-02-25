from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ErrorCategory = Literal[
    "grammar",
    "word_choice",
    "collocation",
    "spelling",
    "cohesion",
    "task_response",
]


class WritingErrorCreate(BaseModel):
    sentence: str = Field(min_length=1)
    correctedSentence: str = Field(min_length=1)
    category: ErrorCategory
    notes: str | None = None
    topic: str | None = None


class WritingErrorOut(BaseModel):
    id: str
    sentence: str
    correctedSentence: str
    category: ErrorCategory
    notes: str | None
    topic: str | None
    count: int
    createdAt: datetime
    updatedAt: datetime


class WritingDeckItem(BaseModel):
    id: str
    sentence: str
    correctedSentence: str
    category: ErrorCategory


class WritingDeckResponse(BaseModel):
    items: list[WritingDeckItem] = Field(default_factory=list)
