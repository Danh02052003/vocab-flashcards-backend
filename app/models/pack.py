from datetime import datetime

from pydantic import BaseModel, Field


class TopicPackCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    topics: list[str] = Field(default_factory=list)
    targetBand: float | None = Field(default=None, ge=1.0, le=9.0)
    vocabIds: list[str] = Field(default_factory=list)


class TopicPackAddVocabRequest(BaseModel):
    vocabId: str


class TopicPackOut(BaseModel):
    id: str
    name: str
    description: str | None
    topics: list[str] = Field(default_factory=list)
    targetBand: float | None
    vocabIds: list[str] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime
