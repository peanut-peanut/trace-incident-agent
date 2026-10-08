import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def redact(text: str) -> str:
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRun(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=8, max_length=4000)
    fixture_id: str | None = None
    logs: str = Field(default="", max_length=12000)
    diff: str = Field(default="", max_length=12000)

    @field_validator("title", "description", "logs", "diff", mode="before")
    @classmethod
    def clean(cls, value):
        return redact(value.strip()) if isinstance(value, str) else value


class Evidence(StrictModel):
    id: str
    kind: Literal["log", "diff", "runbook"]
    title: str
    source: str
    content: str


class Finding(StrictModel):
    hypothesis: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    verification: str = Field(min_length=1, max_length=1500)


class Report(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    severity: Literal["P1", "P2", "P3"]
    confidence: Literal["high", "medium", "low"]
    findings: list[Finding] = Field(max_length=5)
    next_steps: list[str] = Field(min_length=1, max_length=8)
    missing_information: list[str] = Field(max_length=8)


class Decision(StrictModel):
    approved: bool
    title: str = Field(min_length=3, max_length=160)
    note: str = Field(default="", max_length=2000)

    @field_validator("title", "note", mode="before")
    @classmethod
    def clean(cls, value):
        return redact(value.strip()) if isinstance(value, str) else value


class EmptyArgs(StrictModel):
    pass


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=200)
