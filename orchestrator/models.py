from typing import Literal

from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    time: str
    event: str
    evidence: list[str] = Field(default_factory=list)


class RootCause(BaseModel):
    statement: str
    confidence: Literal["high", "medium", "low"]
    evidence: list[str] = Field(default_factory=list)
    correlation: str


class RuledOut(BaseModel):
    theory: str
    why: str
    evidence: list[str] = Field(default_factory=list)


class CorrelationResult(BaseModel):
    symptoms: str
    timeline: list[TimelineEvent] = Field(default_factory=list)
    root_cause: RootCause
    ruled_out: list[RuledOut] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Runbook(BaseModel):
    matched: str | None = None
    title: str | None = None
    source: str | None = None
    why: str
    remediation: list[str] = Field(default_factory=list)


class Action(BaseModel):
    action: str
    urgency: Literal["now", "today", "follow-up"]
    source: str


class IncidentReport(BaseModel):
    incident_id: str
    summary: str
    timeline: list[TimelineEvent]
    root_cause: RootCause
    ruled_out: list[RuledOut]
    runbook: Runbook
    actions: list[Action]
    stakeholder_update: str | None = None
    open_questions: list[str] = Field(default_factory=list)
