from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SyncExport(BaseModel):
    schemaVersion: Literal["v1"] = "v1"
    exportedAt: datetime
    vocabs: list[dict[str, Any]] = Field(default_factory=list)
    review_logs: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class SyncImportReport(BaseModel):
    addedVocabs: int
    updatedVocabs: int
    addedLogs: int
    conflicts: int
