"""Tests for the shared agentic loop engine.

These use a fake mode and a stubbed LLM, so they need no running services and
no API key - which means they can run in CI on every push.

The important one is `test_adapt_retries_and_recovers`: it proves the loop
actually loops. Without it, nothing distinguishes this from a linear pipeline
that happens to use the words Plan/Act/Observe/Adapt.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic import llm, loop  # noqa: E402
from agentic.core import Evidence, Mode, Plan, Verdict  # noqa: E402


class FakeMode(Mode):
    """A mode whose validator rejects any answer not containing 'GROUNDED'."""

    key = "fake"
    label = "Fake"
    owner = "test"

    def __init__(self, evidence: Evidence | None = None):
        self.evidence = evidence or Evidence(ok=True, summary="2 records", facts={"n": 2})
        self.prompts_seen: list[str] = []

    def plan(self) -> Plan:
        return Plan(goal="prove the loop loops", checks=["a check"])

    def collect(self) -> Evidence:
        return self.evidence

    def build_prompt(self, plan, evidence, feedback):
        user = f"do the thing{(' CORRECTION: ' + feedback) if feedback else ''}"
        self.prompts_seen.append(user)
        return "system", user

    def validate(self, output, evidence):
        if "GROUNDED" in output:
            return Verdict(True)
        return Verdict(False, ["it did not cite the evidence"])


STUB_REVIEW = (
    "Risk: No evidence-backed risk identified.\n"
    "Correction: No correction required.\n"
    "Retest: Repeat validation after future changes."
)


@pytest.fixture
def answers(monkeypatch):
    """Stub llm.ask with a scripted list of replies.

    The review call (review=True) is answered separately and does not consume
    from the script, so a test only scripts the answers it cares about.
    """
    scripted: list[str] = []

    def fake_ask(system_prompt, user_prompt, **kwargs):
        if kwargs.get("review"):
            return STUB_REVIEW
        if not scripted:
            raise AssertionError("llm.ask called more times than the script allows")
        return scripted.pop(0)

    monkeypatch.setattr(llm, "ask", fake_ask)
    monkeypatch.setattr(llm, "describe", lambda **kw: "stub/stub")
    return scripted


def test_passes_first_time_without_adapting(answers):
    answers.append("GROUNDED: two records seen.")
    mode = FakeMode()

    result = loop.run(mode)

    assert result.ok
    assert not result.adapted
    assert len(result.attempts) == 1


def test_adapt_retries_and_recovers(answers):
    """The loop rejects a bad answer, feeds the reason back, and succeeds."""
    answers.extend(["vague filler", "GROUNDED: two records seen."])
    mode = FakeMode()

    result = loop.run(mode)

    assert result.ok, "second attempt should pass"
    assert result.adapted, "Adapt stage should have fired"
    assert len(result.attempts) == 2

    # The rejection reason must reach the retry prompt - that is the Adapt stage.
    assert "CORRECTION" in mode.prompts_seen[1]
    assert "did not cite the evidence" in mode.prompts_seen[1]

    assert result.attempts[0].verdict.ok is False
    assert result.attempts[1].verdict.ok is True


def test_gives_up_after_the_retry_budget(answers):
    answers.extend(["filler", "more filler"])
    mode = FakeMode()

    result = loop.run(mode, max_attempts=2)

    assert not result.ok
    assert len(result.attempts) == 2


def test_unusable_evidence_never_calls_the_model(answers):
    """No API call when the app is not in a state worth asking about."""
    mode = FakeMode(Evidence(ok=False, summary="service down"))

    result = loop.run(mode)

    assert not result.ok
    assert result.attempts == []          # nothing was attempted
    assert answers == []                  # and llm.ask was never called


def test_degraded_evidence_still_runs_but_is_flagged(answers):
    answers.append("GROUNDED: from the fallback source.")
    mode = FakeMode(
        Evidence(ok=True, summary="1 record", facts={"n": 1},
                 degraded=True, note="fell back to seed data")
    )

    result = loop.run(mode)

    assert result.ok
    assert result.evidence.degraded
    assert result.evidence.note == "fell back to seed data"


def test_review_runs_on_an_accepted_answer(answers):
    answers.append("GROUNDED: two records seen.")
    mode = FakeMode()

    result = loop.run(mode)

    assert result.ok
    assert result.review.ran
    assert "Risk:" in result.review.text


def test_review_is_skipped_when_the_answer_was_rejected(answers):
    """No point spending a review call on an answer that already failed."""
    answers.extend(["filler", "more filler"])
    mode = FakeMode()

    result = loop.run(mode, max_attempts=2)

    assert not result.ok
    assert not result.review.ran


def test_review_never_overturns_the_verdict(answers, monkeypatch):
    """A scathing review is recorded, but PASS still stands.

    The deterministic validator is the gate; the reviewer is advisory. If the
    reviewer could flip the result, a flaky model would make runs
    non-reproducible in front of a marker.
    """
    answers.append("GROUNDED: two records seen.")

    def harsh(system_prompt, user_prompt, **kwargs):
        if kwargs.get("review"):
            return "Risk: The answer is completely unsupported.\nCorrection: Rewrite it.\nRetest: Everything."
        return answers.pop(0)

    monkeypatch.setattr(llm, "ask", harsh)
    result = loop.run(FakeMode())

    assert result.ok
    assert "completely unsupported" in result.review.text


def test_missing_review_prompt_is_recorded_not_raised(answers, monkeypatch):
    from agentic import prompts as prompts_module

    def missing(*args, **kwargs):
        raise prompts_module.MissingPrompt("Missing prompt file: prompts/_loop/review_system_prompt.txt")

    monkeypatch.setattr(prompts_module, "load_all", missing)
    answers.append("GROUNDED: two records seen.")

    result = loop.run(FakeMode())      # must not raise

    assert result.ok                    # the run still passed
    assert "Missing prompt file" in result.review.error


def test_llm_failure_is_recorded_not_raised(answers, monkeypatch):
    def boom(*args, **kwargs):
        raise llm.LLMUnavailable("GEMINI_API_KEY is not set")

    monkeypatch.setattr(llm, "ask", boom)
    mode = FakeMode()

    result = loop.run(mode)          # must not raise

    assert not result.ok
    assert len(result.attempts) == 1
    assert "GEMINI_API_KEY" in result.attempts[0].error
