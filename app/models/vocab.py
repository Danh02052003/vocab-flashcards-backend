from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class VocabCreate(BaseModel):
    term: str = Field(min_length=1)
    meanings: list[str] = Field(default_factory=list)
    ipa: str | None = None
    exampleEn: str | None = None
    exampleVi: str | None = None
    mnemonic: str | None = None
    tags: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)
    wordFamily: dict[str, list[str]] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    cefrLevel: CEFRLevel | None = None
    ieltsBand: float | None = Field(default=None, ge=1.0, le=9.0)
    inputMethod: Literal["typed", "pasted"] = "pasted"


class VocabUpdate(BaseModel):
    term: str | None = None
    meanings: list[str] | None = None
    ipa: str | None = None
    exampleEn: str | None = None
    exampleVi: str | None = None
    mnemonic: str | None = None
    tags: list[str] | None = None
    collocations: list[str] | None = None
    phrases: list[str] | None = None
    wordFamily: dict[str, list[str]] | None = None
    topics: list[str] | None = None
    cefrLevel: CEFRLevel | None = None
    ieltsBand: float | None = Field(default=None, ge=1.0, le=9.0)


class VocabUpsertWithAiRequest(BaseModel):
    term: str = Field(min_length=1)
    meanings: list[str] = Field(default_factory=list)
    ipa: str | None = None
    exampleEn: str | None = None
    exampleVi: str | None = None
    mnemonic: str | None = None
    tags: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)
    wordFamily: dict[str, list[str]] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    cefrLevel: CEFRLevel | None = None
    ieltsBand: float | None = Field(default=None, ge=1.0, le=9.0)
    inputMethod: Literal["typed", "pasted"] = "pasted"
    overwriteExisting: bool = True
    useAi: bool = True
    forceAi: bool = False


class VocabOut(BaseModel):
    id: str
    term: str
    termNormalized: str
    meanings: list[str]
    ipa: str | None
    exampleEn: str | None
    exampleVi: str | None
    mnemonic: str | None
    tags: list[str]
    collocations: list[str]
    phrases: list[str]
    wordFamily: dict[str, list[str]]
    topics: list[str]
    cefrLevel: str | None
    ieltsBand: float | None
    createdAt: datetime
    updatedAt: datetime
    easeFactor: float
    intervalDays: int
    repetitions: int
    lapses: int
    dueAt: datetime
    lastReviewedAt: datetime | None
    readdCount: int
    lastReaddAt: datetime | None


class SessionOut(BaseModel):
    todayNew: list[VocabOut]
    review: list[VocabOut]


class VocabUpsertWithAiOut(BaseModel):
    action: Literal["created", "updated"]
    overwritten: bool
    vocab: VocabOut
    ai: dict[str, Any]
    suggestions: dict[str, Any]


def vocab_doc_to_out(doc: dict[str, Any]) -> VocabOut:
    return VocabOut(
        id=str(doc["_id"]),
        term=doc.get("term", ""),
        termNormalized=doc.get("termNormalized", ""),
        meanings=doc.get("meanings", []) or [],
        ipa=doc.get("ipa"),
        exampleEn=doc.get("exampleEn"),
        exampleVi=doc.get("exampleVi"),
        mnemonic=doc.get("mnemonic"),
        tags=doc.get("tags", []) or [],
        collocations=doc.get("collocations", []) or [],
        phrases=doc.get("phrases", []) or [],
        wordFamily=doc.get("wordFamily", {}) or {},
        topics=doc.get("topics", []) or [],
        cefrLevel=doc.get("cefrLevel"),
        ieltsBand=float(doc.get("ieltsBand")) if doc.get("ieltsBand") is not None else None,
        createdAt=doc["createdAt"],
        updatedAt=doc["updatedAt"],
        easeFactor=float(doc.get("easeFactor", 2.5)),
        intervalDays=int(doc.get("intervalDays", 0)),
        repetitions=int(doc.get("repetitions", 0)),
        lapses=int(doc.get("lapses", 0)),
        dueAt=doc["dueAt"],
        lastReviewedAt=doc.get("lastReviewedAt"),
        readdCount=int(doc.get("readdCount", 0)),
        lastReaddAt=doc.get("lastReaddAt"),
    )
