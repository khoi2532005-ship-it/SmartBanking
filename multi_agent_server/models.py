"""Shared vocabulary for the Multi-Agent Server: workflow states and records.

A workflow moves through the Lecture 10 stages in order. Each stage leaves a
StageRecord (who ran, which model, how long, what came out), so the workflow
is traceable end to end and every stage can be reviewed or repeated.
"""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class State:
    CREATED = "created"
    PLANNING = "planning"
    PLANNED = "planned"
    WORKING = "working"
    EXECUTED = "executed"
    REVIEWING = "reviewing"
    REVISING = "revising"
    REVIEWED = "reviewed"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    ACCEPTED = "accepted"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"
    FAILED = "failed"

    ALL = (CREATED, PLANNING, PLANNED, WORKING, EXECUTED, REVIEWING, REVISING, REVIEWED,
           AWAITING_HUMAN_REVIEW, ACCEPTED, PARTIALLY_ACCEPTED, REJECTED, FAILED)
    RUNNING = (PLANNING, PLANNED, WORKING, EXECUTED, REVIEWING, REVISING, REVIEWED)
    TERMINAL = (ACCEPTED, PARTIALLY_ACCEPTED, REJECTED, FAILED)


# The human's three answers (Lecture 10) and the state each one ends in.
DECISIONS = {
    "accept": State.ACCEPTED,
    "partially_accept": State.PARTIALLY_ACCEPTED,
    "reject": State.REJECTED,
}
MAX_NOTE_CHARS = 1000
MAX_BY_CHARS = 100
CONTEXT_KEYS = ("customer_id", "month", "year")      # the only context a workflow carries
CONTEXT_BOUNDS = {"customer_id": (1, None), "month": (1, 12), "year": (2000, 2100)}


def clean_text(value: Any, name: str, max_chars: int) -> tuple[str, str | None]:
    """A text field a person typed: a real string, UTF-8 encodable, within bounds.

    JSON accepts unpaired surrogates ("\\ud83d"), which no UTF-8 writer can store;
    they are refused here so a request or decision can never half-apply.
    """
    if value is None:
        return "", None
    if not isinstance(value, str):
        return "", f"{name} must be a string"
    text = value.strip()
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "", f"{name} is not valid text (unpaired surrogate)"
    if len(text) > max_chars:
        return "", f"{name} must be {max_chars} characters or fewer"
    return text, None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seconds_between(start_iso: str, end_iso: str) -> float | None:
    """Elapsed seconds between two stored timestamps (the human stage can span a restart)."""
    try:
        return round((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds(), 3)
    except (TypeError, ValueError):
        return None


def new_workflow_id() -> str:
    """Short, unique and easy to read back from a log: wf_8f3a2b7c."""
    return "wf_" + secrets.token_hex(4)


@dataclass
class StageRecord:
    role: str                     # planner | worker | reviewer | human
    attempt: int
    started_at: str
    finished_at: str = ""
    model: str = ""
    status: str = "running"       # running | completed | failed | timed_out
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_seconds: float | None = None
    fallback: bool = False            # the stage answered with its deterministic fallback
    fallback_reason: str = ""


@dataclass
class Workflow:
    workflow_id: str
    feature: str
    request: str
    context: dict[str, Any]
    state: str = State.CREATED
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    stages: list[StageRecord] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    revisions: int = 0
    decision: dict[str, Any] | None = None
    final_response: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        stages = [StageRecord(**s) for s in data.get("stages", [])]
        fields = {k: v for k, v in data.items() if k != "stages"}
        return cls(stages=stages, **fields)

    def summary(self) -> dict[str, Any]:
        """The compact view GET /workflow/<id>/status returns and the UI polls."""
        return {
            "workflow_id": self.workflow_id,
            "feature": self.feature,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revisions": self.revisions,
            "stages": [
                {"role": s.role, "attempt": s.attempt, "status": s.status, "model": s.model,
                 "duration_seconds": s.duration_seconds, "fallback": s.fallback}
                for s in self.stages
            ],
            "has_plan": self.plan is not None,
            "has_result": self.result is not None,
            "has_review": self.review is not None,
            "decision": self.decision,
            "released": bool(self.final_response and self.final_response.get("released")),
            "error": self.error,
        }
