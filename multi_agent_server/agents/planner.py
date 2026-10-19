"""Planner: turns one request into an ordered plan the other roles can check.

Role boundary: the Planner only plans. It receives the request, the context
and the endpoint catalogue for the feature, and returns tasks the Worker will
execute and the Reviewer will check. Its output must satisfy the plan contract
in contracts.py; it gets one correction attempt. If the model is unavailable,
too slow or still off-contract, a deterministic fallback plan built from the
catalogue's default endpoints keeps the workflow moving, flagged as such in
the plan's meta and in both audit files.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from agentic.llm import LLMUnavailable
from multi_agent_server import catalogue
from multi_agent_server.agents import base
from multi_agent_server.catalogue import CONTEXT_PARAMS
from multi_agent_server.contracts import ContractError, parse_json_object, validate_plan
from multi_agent_server.models import Workflow, now_iso

ROLE = "planner"
MAX_ATTEMPTS = 2          # the first plan plus one correction


@dataclass
class PlanResult:
    plan: dict[str, Any]
    model: str
    attempts: int
    source: str                               # model | fallback
    accepted_first_try: bool
    rejections: list[list[str]] = field(default_factory=list)
    fallback_reason: str = ""
    duration_seconds: float = 0.0


def build_prompts(workflow: Workflow, feedback: str = "") -> tuple[str, str]:
    """System and task prompt for one attempt; `feedback` lists contract errors."""
    system, task = base.load_prompts(ROLE)
    block = ""
    if feedback:
        block = ("\nYour previous plan was rejected by the handoff contract for these reasons:\n"
                 f"{feedback}\nFix every item and return the complete JSON object again.\n")
    user = task.substitute(
        feature=workflow.feature,
        request=workflow.request,
        context=json.dumps(workflow.context, sort_keys=True),
        catalogue=catalogue.describe(workflow.feature),
        feedback=block,
    )
    return system, user


def plan(workflow: Workflow, *, ask: base.AskFn | None = None) -> PlanResult:
    started = time.monotonic()
    model = base.model_for(ROLE)
    rejections: list[list[str]] = []
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        system, user = build_prompts(workflow, feedback)
        try:
            text = base.call_model(ROLE, system, user, ask=ask)
        except LLMUnavailable as exc:
            return fallback_result(workflow, f"model unavailable: {exc}", model=model,
                                   attempts=attempt, rejections=rejections, started=started)
        try:
            accepted = validate_plan(parse_json_object(text), workflow.feature, workflow.context)
        except ContractError as exc:
            rejections.append(exc.errors)
            feedback = "\n".join(f"- {error}" for error in exc.errors)
            continue
        duration = round(time.monotonic() - started, 3)
        accepted["meta"] = _meta("model", model, attempt, rejections, "", duration)
        return PlanResult(plan=accepted, model=model, attempts=attempt, source="model",
                          accepted_first_try=attempt == 1, rejections=rejections,
                          duration_seconds=duration)
    return fallback_result(workflow, f"plan rejected by the contract {MAX_ATTEMPTS} times",
                           model=model, attempts=MAX_ATTEMPTS, rejections=rejections, started=started)


def fallback_result(workflow: Workflow, reason: str, *, model: str = "", attempts: int = 0,
                    rejections: list[list[str]] | None = None, started: float | None = None) -> PlanResult:
    """The deterministic plan, packaged like a model plan but flagged."""
    duration = round(time.monotonic() - started, 3) if started is not None else 0.0
    fallback = fallback_plan(workflow.feature, workflow.context)
    fallback["meta"] = _meta("fallback", model or base.model_for(ROLE), attempts, rejections or [], reason, duration)
    return PlanResult(plan=fallback, model=model, attempts=attempts, source="fallback",
                      accepted_first_try=False, rejections=rejections or [],
                      fallback_reason=reason, duration_seconds=duration)


def fallback_plan(feature: str, context: dict[str, Any]) -> dict[str, Any]:
    """A valid plan from the catalogue's default endpoints; no model involved.

    Period values missing from the context default to the current month, the
    same default the feature APIs apply themselves.
    """
    today = date.today()
    values = {"month": today.month, "year": today.year, **{k: v for k, v in context.items() if k in CONTEXT_PARAMS}}
    tasks: list[dict[str, Any]] = []
    for entry in catalogue.default_endpoints(feature):
        params = {name: values[name] for name in entry["params"] if name in CONTEXT_PARAMS and name in values}
        if any(name not in params for name in entry["required"]):
            continue
        tasks.append({
            "id": f"t{len(tasks) + 1}",
            "kind": "api",
            "title": f"Read {entry['path']}",
            "endpoint": entry["path"],
            "params": params,
            "evidence": "The response, summarised the way the feature's MCP tool summarises it",
        })
    tasks.append({
        "id": f"t{len(tasks) + 1}",
        "kind": "analysis",
        "title": "Answer the request from the evidence",
        "depends_on": [task["id"] for task in tasks],
        "instruction": "State what the collected evidence shows about the request, and say plainly what it cannot show.",
        "evidence": "Findings, each citing the task whose evidence supports it",
    })
    return validate_plan({
        "objective": f"Answer the {feature} request from the feature's default read-only endpoints",
        "tasks": tasks,
        "success_criteria": [
            f"Every default {feature} endpoint answered and its evidence was recorded",
            "Each finding cites the task whose evidence supports it",
        ],
        "limitations": ["Fallback plan built from the catalogue defaults, not from the request wording"],
    }, feature, context)


def _meta(source: str, model: str, attempts: int, rejections: list[list[str]], reason: str,
          duration: float) -> dict[str, Any]:
    return {
        "role": ROLE,
        "source": source,
        "model": model,
        "attempts": attempts,
        "accepted_first_try": source == "model" and attempts == 1,
        "rejections": rejections,
        "fallback_reason": reason,
        "duration_seconds": duration,
        "created_at": now_iso(),
    }
