from pydantic import BaseModel, Field


class UserStatsOut(BaseModel):
    streak: int
    lastActivityDate: str
    totalReviewed: int
    totalCorrect: int
    accuracy: int
    dailyNewCreatedCount: int
    dailyNewCreatedDate: str
    dailyStudyLockCompletedCount: int
    dailyStudyLockCompletedDate: str
    studyLockTargetPerDay: int
    studyLockIntervalMinutes: int


class ReviewCompletedRequest(BaseModel):
    total: int = Field(ge=0, le=1000)
    passed: int = Field(ge=0, le=1000)


class VocabCreatedRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=1000)


class StudyLockCompletedRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=1000)


class StudySettingsRequest(BaseModel):
    studyLockTargetPerDay: int = Field(default=5, ge=1, le=100)
    studyLockIntervalMinutes: int = Field(default=45, ge=5, le=240)

