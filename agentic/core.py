"""Shared vocabulary for the agentic loop.

One set of types so the engine in `agentic/loop.py` can drive any feature's
mode without knowing what the feature actually does. A mode supplies four
small functions (plan / collect / build_prompt / validate); the engine owns
the loop, the retries and the evidence log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Plan:
    """PLAN - what this run intends to check, decided before anything executes."""

    goal: str
    checks: list[str] = field(default_factory=list)
    stop_condition: str = ""


@dataclass
class Evidence:
    """ACT output - deterministic facts gathered without asking the LLM anything.

    `ok=False` means the evidence could not be gathered at all (service down,
    database missing) and the run stops before spending an API call.

    `degraded=True` means it *was* gathered, but from a fallback source. The
    run continues and says so, rather than reporting a clean pass it did not
    earn - this is the "fall back to the seed and mark the result degraded"
    behaviour the build spec asks for.
    """

    ok: bool
    summary: str
    facts: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    note: str = ""


@dataclass
class Verdict:
    """OBSERVE output - did the model's answer survive checking against evidence?

    `reasons` are fed back into the next attempt's prompt, so write them as
    instructions to the model, not as log lines. "did not name the triggered
    rule" is useful; "validation failed" is not.
    """

    ok: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class Attempt:
    """One pass through ACT -> OBSERVE. Attempt 2+ exists because ADAPT fired."""

    n: int
    output: str
    verdict: Verdict
    adapt_note: str = ""
    error: str = ""


@dataclass
class Review:
    """Second opinion from the review model on the accepted answer.

    Advisory, not a gate. `validate()` is the deterministic check that drives
    the retry; this catches the qualitative things a string check cannot - an
    answer that names the right rule and amount but describes what the rule
    does incorrectly. Recorded in the evidence log either way.
    """

    text: str = ""
    model: str = ""
    error: str = ""

    @property
    def ran(self) -> bool:
        return bool(self.text or self.error)


@dataclass
class Result:
    mode: str
    plan: Plan
    evidence: Evidence
    attempts: list[Attempt] = field(default_factory=list)
    review: Review = field(default_factory=Review)

    @property
    def ok(self) -> bool:
        return bool(self.attempts) and self.attempts[-1].verdict.ok

    @property
    def adapted(self) -> bool:
        """True when the loop had to correct itself - the demonstrable bit.

        An Adapt branch that never visibly fires is hard to demo, so the
        reporter calls this out explicitly.
        """
        return len(self.attempts) > 1

    @property
    def final_output(self) -> str:
        return self.attempts[-1].output if self.attempts else ""


class Mode:
    """One feature's slice of the shared loop.

    Subclass this in `agentic/modes/<feature>.py`, implement the four methods,
    and register it in `agentic/modes/__init__.py`. That is the whole contract -
    the engine owns the loop, the retry budget, the reporting and the evidence
    log, so a feature owner never writes any of that.

    Copy `agentic/modes/_template.py` to start.
    """

    key: str = ""       # menu key and evidence-log filename, e.g. "fraud"
    label: str = ""     # human label, e.g. "Fraud Alerts"
    owner: str = ""     # student name, so the showcase menu says who demos what

    def plan(self) -> Plan:
        """PLAN - state the goal and the checks before anything runs."""
        raise NotImplementedError

    def collect(self) -> Evidence:
        """ACT (deterministic half) - gather facts from your DB and endpoints.

        No LLM calls here. If this returns `ok=False` the engine stops before
        spending an API call, which is what you want when a service is down.
        """
        raise NotImplementedError

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        """ACT (LLM half) - return (system_prompt, user_prompt).

        `feedback` is empty on the first attempt. On a retry it carries the
        Verdict reasons from the failed attempt: append it to the user prompt
        so the model is told what to fix. That append *is* the Adapt stage.
        """
        raise NotImplementedError

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        """OBSERVE - check the model's answer against the evidence.

        Check the answer is grounded in the facts you collected, not just that
        the call returned 200. Phrase failure reasons as instructions to the
        model - they are fed straight back into the retry prompt.
        """
        raise NotImplementedError
