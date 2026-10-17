"""Reviewer: judges the Worker's result against the plan and the evidence.

Role boundary: the Reviewer evaluates. It does not plan, fetch or rewrite.
Its verdict is bound by a completion gate enforced in code (contracts.py):
"accept" is only valid when every success criterion is met and no defect is
high severity; anything else is "revise" with notes the Worker can act on.
One correction attempt, then a fallback review that escalates to the human
instead of inventing a verdict: a review the model could not make is recorded
as such, with the deterministic checks the human can still rely on.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from agentic.llm import LLMUnavailable
from multi_agent_server import config
from multi_agent_server.agents import base, worker
from multi_agent_server.contracts import ContractError, parse_json_object, validate_review
from multi_agent_server.models import Workflow, now_iso

ROLE = "reviewer"
MAX_ATTEMPTS = 2          # the first review plus one correction
MAX_TOKENS = 2000
ESCALATE = "escalate"     # fallback verdict: the human decides without a model review


@dataclass
class ReviewResult:
    review: dict[str, Any]
    model: str
    attempts: int
    source: str                               # model | fallback
    accepted_first_try: bool
    rejections: list[list[str]] = field(default_factory=list)
    fallback_reason: str = ""
    duration_seconds: float = 0.0


def checks(workflow: Workflow, attempt: int, max_revisions: int | None = None) -> dict[str, Any]:
    """Facts the server establishes before any model judges the result."""
    plan = workflow.plan or {}
    result = workflow.result or {}
    records = result.get("evidence", [])
    ok = [r for r in records if r["status"] == "ok"]
    return {
        "attempt": attempt,
        "revisions_so_far": workflow.revisions,
        "max_revisions": config.MAX_REVISIONS if max_revisions is None else max_revisions,
        "evidence_tasks": len(records),
        "evidence_ok": len(ok),
        "evidence_failed": len(records) - len(ok),
        "finding_count": len(result.get("findings", [])),
        "gap_count": len(result.get("gaps", [])),
        "answer_present": bool(result.get("answer")),
        "request_only_numbers": result.get("request_only_numbers", []),
        "plan_source": (plan.get("meta") or {}).get("source", "unknown"),
        "result_source": (result.get("meta") or {}).get("source", "unknown"),
        "spending_sources": sorted({str(r["summary"].get("spending_source")) for r in ok
                                    if isinstance(r.get("summary"), dict) and "spending_source" in r["summary"]}),
    }


def build_prompts(workflow: Workflow, facts: dict[str, Any], feedback: str = "") -> tuple[str, str]:
    system, task = base.load_prompts(ROLE)
    plan = workflow.plan or {}
    result = workflow.result or {}
    user = task.substitute(
        feature=workflow.feature,
        request=workflow.request,
        objective=plan.get("objective", ""),
        limitations="; ".join(plan.get("limitations", [])) or "none stated",
        success_criteria="\n".join(f"{i}. {c}" for i, c in enumerate(plan.get("success_criteria", []), start=1))
        or "(none given)",
        checks="\n".join(f"- {k}: {json.dumps(v)}" for k, v in facts.items()),
        findings="\n".join(f"- {f['task_id']} (evidence {', '.join(f['evidence'])}): {f['statement']}"
                           for f in result.get("findings", [])) or "(none)",
        answer=result.get("answer") or "(none)",
        gaps="\n".join(f"- {g}" for g in result.get("gaps", [])) or "(none)",
        evidence="\n".join(worker.render_evidence(r) for r in result.get("evidence", [])) or "(no evidence collected)",
        feedback=feedback,
    )
    return system, user


def review(workflow: Workflow, *, attempt: int = 1, ask: base.AskFn | None = None,
           max_revisions: int | None = None) -> ReviewResult:
    started = time.monotonic()
    model = base.model_for(ROLE)
    facts = checks(workflow, attempt, max_revisions)
    rejections: list[list[str]] = []
    correction = ""
    for call in range(1, MAX_ATTEMPTS + 1):
        system, user = build_prompts(workflow, facts, _feedback_block(correction))
        try:
            text = base.call_model(ROLE, system, user, ask=ask, max_tokens=MAX_TOKENS)
        except LLMUnavailable as exc:
            return fallback_result(workflow, f"model unavailable: {exc}", model=model, attempts=call,
                                   rejections=rejections, attempt=attempt, started=started,
                                   max_revisions=max_revisions)
        try:
            accepted = validate_review(parse_json_object(text), workflow.plan or {},
                                       (workflow.result or {}).get("evidence", []),
                                       request=workflow.request, context=workflow.context)
        except ContractError as exc:
            rejections.append(exc.errors)
            correction = "\n".join(f"- {error}" for error in exc.errors)
            continue
        duration = round(time.monotonic() - started, 3)
        accepted.update({"checks": facts, "escalated": False, "escalation_reason": "",
                         "meta": _meta("model", model, call, rejections, "", duration, attempt)})
        return ReviewResult(review=accepted, model=model, attempts=call, source="model",
                            accepted_first_try=call == 1, rejections=rejections, duration_seconds=duration)
    return fallback_result(workflow, f"review rejected by the contract {MAX_ATTEMPTS} times", model=model,
                           attempts=MAX_ATTEMPTS, rejections=rejections, attempt=attempt, started=started,
                           max_revisions=max_revisions)


def fallback_result(workflow: Workflow, reason: str, *, model: str = "", attempts: int = 0,
                    rejections: list[list[str]] | None = None, attempt: int = 1,
                    started: float | None = None, max_revisions: int | None = None) -> ReviewResult:
    """No verdict is invented: the review escalates to the human with the facts."""
    duration = round(time.monotonic() - started, 3) if started is not None else 0.0
    facts = checks(workflow, attempt, max_revisions)
    reason = reason.rstrip(".")
    risks = [f"Review not performed: {reason}"]
    if facts["result_source"] != "model":
        risks.append("The Worker result contains no model analysis; the findings are the evidence summaries")
    if facts["evidence_failed"]:
        risks.append(f"{facts['evidence_failed']} of {facts['evidence_tasks']} evidence calls failed")
    if facts["request_only_numbers"]:
        risks.append("Figures " + ", ".join(facts["request_only_numbers"])
                     + " come from the request, not from the evidence; check how the answer uses them")
    if "mock" in facts["spending_sources"]:
        risks.append("Spending figures come from the budgeting service's mock dataset, not the Transactions API")
    plan = workflow.plan or {}
    fallback = {
        "verdict": ESCALATE,
        "summary": f"The Reviewer could not evaluate the result ({reason}); a human decision is required.",
        "criteria": [{"index": i, "met": None, "note": "not evaluated"}
                     for i in range(1, len(plan.get("success_criteria", [])) + 1)],
        "defects": [],
        "risks": risks,
        "revision_notes": [],
        "checks": facts,
        "escalated": True,
        "escalation_reason": reason,
        "meta": _meta("fallback", model or base.model_for(ROLE), attempts, rejections or [], reason, duration, attempt),
    }
    return ReviewResult(review=fallback, model=model, attempts=attempts, source="fallback",
                        accepted_first_try=False, rejections=rejections or [], fallback_reason=reason,
                        duration_seconds=duration)


def _feedback_block(correction: str) -> str:
    if not correction:
        return ""
    return ("\nYour previous review was rejected by the handoff contract for these reasons:\n"
            f"{correction}\nFix every item and return the complete JSON object again.\n")


def _meta(source: str, model: str, attempts: int, rejections: list[list[str]], reason: str,
          duration: float, attempt: int) -> dict[str, Any]:
    return {
        "role": ROLE,
        "source": source,
        "model": model,
        "attempt": attempt,
        "attempts": attempts,
        "accepted_first_try": source == "model" and attempts == 1,
        "rejections": rejections,
        "fallback_reason": reason,
        "duration_seconds": duration,
        "created_at": now_iso(),
    }
