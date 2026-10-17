"""Worker: executes the accepted plan and answers from the evidence.

Role boundary: the Worker does not plan and does not judge. It runs the
plan's api tasks over the feature APIs (evidence.py), then completes the
analysis tasks in one model call whose output must satisfy the result
contract: every finding names its analysis task and the api tasks it rests
on, and every figure must appear in the evidence. One correction attempt,
then a deterministic result built from the evidence keeps the workflow
moving, flagged as a fallback. On a revision the Reviewer's notes are added
to the prompt.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from agentic.llm import LLMUnavailable
from multi_agent_server.agents import base
from multi_agent_server.contracts import ContractError, parse_json_object, validate_result
from multi_agent_server.models import Workflow, now_iso

ROLE = "worker"
MAX_ATTEMPTS = 2          # the first result plus one correction
MAX_TOKENS = 2000


@dataclass
class WorkResult:
    result: dict[str, Any]
    model: str
    attempts: int
    source: str                               # model | fallback
    accepted_first_try: bool
    rejections: list[list[str]] = field(default_factory=list)
    fallback_reason: str = ""
    duration_seconds: float = 0.0


def build_prompts(workflow: Workflow, evidence: list[dict[str, Any]], feedback: str = "") -> tuple[str, str]:
    system, task = base.load_prompts(ROLE)
    plan = workflow.plan or {}
    analysis = [t for t in plan.get("tasks", []) if t["kind"] == "analysis"]
    user = task.substitute(
        feature=workflow.feature,
        request=workflow.request,
        objective=plan.get("objective", ""),
        success_criteria="\n".join(f"- {c}" for c in plan.get("success_criteria", [])) or "- (none given)",
        analysis_tasks="\n".join(
            f"- {t['id']} \"{t['title']}\" (depends on {', '.join(t['depends_on'])}): {t['instruction']}"
            + (f" Evidence to record: {t['evidence']}" if t.get("evidence") else "")
            for t in analysis) or "- (none: write the answer from the evidence)",
        evidence="\n".join(render_evidence(record) for record in evidence) or "(no evidence collected)",
        feedback=feedback,
    )
    return system, user


def render_evidence(record: dict[str, Any]) -> str:
    head = f"{record['task_id']} GET {record['endpoint']} {json.dumps(record['params'], sort_keys=True)}"
    if record["status"] != "ok":
        return f"{head} -> error: {record['error']}"
    return (f"{head} -> ok, HTTP {record['http_status']}, {record['duration_seconds']}s\n"
            + json.dumps(record["summary"], indent=1, sort_keys=True, ensure_ascii=False))


def analyse(workflow: Workflow, evidence: list[dict[str, Any]], *, feedback: str = "",
            attempt: int = 1, ask: base.AskFn | None = None) -> WorkResult:
    started = time.monotonic()
    model = base.model_for(ROLE)
    rejections: list[list[str]] = []
    correction = ""
    for call in range(1, MAX_ATTEMPTS + 1):
        system, user = build_prompts(workflow, evidence, _feedback_block(feedback, correction))
        try:
            text = base.call_model(ROLE, system, user, ask=ask, max_tokens=MAX_TOKENS)
        except LLMUnavailable as exc:
            return fallback_result(workflow, evidence, f"model unavailable: {exc}", model=model,
                                   attempts=call, rejections=rejections, attempt=attempt, started=started)
        try:
            accepted = validate_result(parse_json_object(text), workflow.plan or {}, evidence,
                                       request=workflow.request, context=workflow.context)
        except ContractError as exc:
            rejections.append(exc.errors)
            correction = "\n".join(f"- {error}" for error in exc.errors)
            continue
        duration = round(time.monotonic() - started, 3)
        result = _package(accepted, evidence, _meta("model", model, call, rejections, "", duration, attempt))
        return WorkResult(result=result, model=model, attempts=call, source="model",
                          accepted_first_try=call == 1, rejections=rejections, duration_seconds=duration)
    return fallback_result(workflow, evidence, f"result rejected by the contract {MAX_ATTEMPTS} times",
                           model=model, attempts=MAX_ATTEMPTS, rejections=rejections, attempt=attempt, started=started)


def fallback_result(workflow: Workflow, evidence: list[dict[str, Any]], reason: str, *, model: str = "",
                    attempts: int = 0, rejections: list[list[str]] | None = None, attempt: int = 1,
                    started: float | None = None) -> WorkResult:
    """Findings written from the evidence itself, with no model involved."""
    duration = round(time.monotonic() - started, 3) if started is not None else 0.0
    findings, answer, gaps = fallback_findings(workflow.plan or {}, evidence, reason)
    meta = _meta("fallback", model or base.model_for(ROLE), attempts, rejections or [], reason, duration, attempt)
    result = _package({"findings": findings, "answer": answer, "gaps": gaps}, evidence, meta)
    return WorkResult(result=result, model=model, attempts=attempts, source="fallback",
                      accepted_first_try=False, rejections=rejections or [], fallback_reason=reason,
                      duration_seconds=duration)


def fallback_findings(plan: dict[str, Any], evidence: list[dict[str, Any]], reason: str
                      ) -> tuple[list[dict[str, Any]], str, list[str]]:
    by_id = {record["task_id"]: record for record in evidence}
    ok_ids = [record["task_id"] for record in evidence if record["status"] == "ok"]
    findings = []
    for task in plan.get("tasks", []):
        if task["kind"] != "analysis":
            continue
        refs = [d for d in task.get("depends_on", []) if d in ok_ids] or ok_ids
        parts = []
        for ref in refs:
            record = by_id[ref]
            scalars = ", ".join(f"{k} {v}" for k, v in record["summary"].items()
                                if isinstance(v, (int, float, str)) and not isinstance(v, bool))
            parts.append(f"{ref} GET {record['endpoint']}: {scalars}"[:400])
        findings.append({"task_id": task["id"], "statement": "; ".join(parts) or "No evidence available",
                         "evidence": refs})
    reason = reason.rstrip(".")
    answer = (f"Evidence was collected from {len(ok_ids)} of {len(evidence)} planned endpoints; the findings "
              f"list what each one returned. No model analysis is included: {reason}.")
    gaps = [f"No model analysis: {reason}"]
    return findings, answer, gaps


def blocked_result(evidence: list[dict[str, Any]], reason: str, attempt: int) -> dict[str, Any]:
    """Stored when no feature API answered: the evidence errors are the result."""
    meta = _meta("blocked", base.model_for(ROLE), 0, [], reason, 0.0, attempt)
    return _package({"findings": [], "answer": "", "gaps": []}, evidence, meta)


def _feedback_block(revision_notes: str, correction: str) -> str:
    block = ""
    if revision_notes:
        block += f"\nThe Reviewer sent the previous result back with these notes; address every one:\n{revision_notes}\n"
    if correction:
        block += ("\nYour previous result was rejected by the handoff contract for these reasons:\n"
                  f"{correction}\nFix every item and return the complete JSON object again.\n")
    return block


def _package(accepted: dict[str, Any], evidence: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    failed = [f"{r['task_id']} {r['endpoint']}: {r['error']}" for r in evidence if r["status"] != "ok"]
    gaps = list(accepted.get("gaps", []))
    for item in failed:
        if item not in gaps:
            gaps.append(item)
    return {"evidence": evidence, "findings": accepted["findings"], "answer": accepted["answer"],
            "gaps": gaps, "request_only_numbers": accepted.get("request_only_numbers", []), "meta": meta}


def _meta(source: str, model: str, attempts: int, rejections: list[list[str]], reason: str,
          duration: float, attempt: int) -> dict[str, Any]:
    return {
        "role": ROLE,
        "source": source,
        "model": model,
        "attempt": attempt,                       # 1, or 2 after a revision
        "attempts": attempts,                     # model calls made in this attempt
        "accepted_first_try": source == "model" and attempts == 1,
        "rejections": rejections,
        "fallback_reason": reason,
        "duration_seconds": duration,
        "created_at": now_iso(),
    }
