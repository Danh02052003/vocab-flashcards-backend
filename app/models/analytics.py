from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    days: int
    totalVocabs: int
    dueNow: int
    reviewedCount: int
    avgGrade: float
    accuracyRate: float
    typingAccuracy: float


class TopicStat(BaseModel):
    topic: str
    vocabCount: int
    reviewedCount: int
    avgGrade: float
