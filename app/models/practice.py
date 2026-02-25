from datetime import datetime
from pydantic import BaseModel, Field


class ClozeGenerateRequest(BaseModel):
    vocabIds: list[str] = Field(default_factory=list)
    topic: str | None = None
    limit: int = Field(default=5, ge=1, le=30)


class ClozeItem(BaseModel):
    vocabId: str
    term: str
    ipa: str | None = None
    question: str
    hint: str | None = None
    acceptableAnswers: list[str] = Field(default_factory=list)


class ClozeGenerateResponse(BaseModel):
    items: list[ClozeItem] = Field(default_factory=list)


class ClozeSubmitRequest(BaseModel):
    vocabId: str
    userAnswer: str = Field(min_length=1)


class ClozeSubmitResponse(BaseModel):
    correct: bool
    nearCorrect: bool
    expected: str


class SpeakingFeedbackRequest(BaseModel):
    prompt: str = Field(min_length=1)
    responseText: str = Field(min_length=1)
    targetWords: list[str] = Field(default_factory=list)


class SpeakingFeedbackResponse(BaseModel):
    estimatedBand: float
    targetCoverage: float
    usedTargetWords: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reasonShort: str
    provider: str
    createdAt: datetime
