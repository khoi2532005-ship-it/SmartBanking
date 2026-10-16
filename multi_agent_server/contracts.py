"""Handoff contracts (Lecture 10): what one role must hand the next.

A contract is checked by code, not by another model. The Planner's plan is
validated against the endpoint catalogue and the workflow context before the
Worker ever sees it, so a plan that names an unknown endpoint, an undeclared
parameter or another customer is rejected with the reasons, and the model
gets one chance to correct it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from multi_agent_server import catalogue
from multi_agent_server.catalogue import CONTEXT_PARAMS

MIN_TASKS = 1
MAX_TASKS = 6
TASK_KINDS = ("api", "analysis")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ContractError(ValueError):
    """The output did not satisfy the handoff contract; `errors` lists why."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_json_object(text: str) -> dict[str, Any]:
    """Accept the JSON object a model returned, with or without code fences."""
    cleaned = _FENCE.sub("", (text or "").strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ContractError(["output is not a JSON object"])
    try:
        data = json.loads(cleaned[start:end + 1])
    except ValueError as exc:
        raise ContractError([f"output is not valid JSON: {exc}"]) from None
    if not isinstance(data, dict):
        raise ContractError(["output is not a JSON object"])
    return data


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return [v.strip() for v in value if v.strip()]


def validate_plan(plan: dict[str, Any], feature: str, context: dict[str, Any]) -> dict[str, Any]:
    """Return the normalised plan, or raise ContractError listing every problem.

    Unknown keys are dropped; wrong endpoints, undeclared parameters, values
    that disagree with the context and broken dependencies are errors.
    """
    errors: list[str] = []
    objective = str(plan.get("objective") or "").strip()
    if not objective:
        errors.append("objective is required")

    raw_tasks = plan.get("tasks")
    if not isinstance(raw_tasks, list) or not (MIN_TASKS <= len(raw_tasks) <= MAX_TASKS):
        errors.append(f"tasks must be a list of {MIN_TASKS} to {MAX_TASKS} tasks")
        raw_tasks = []

    tasks: list[dict[str, Any]] = []
    seen: list[str] = []
    for index, raw in enumerate(raw_tasks, start=1):
        label = f"task {index}"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be an object")
            continue
        task_id = str(raw.get("id") or "").strip()
        if not task_id:
            errors.append(f"{label} needs an id")
        elif task_id in seen:
            errors.append(f"{label}: duplicate id {task_id!r}")
        label = f"task {task_id or index}"
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in TASK_KINDS:
            errors.append(f"{label}: kind must be one of {list(TASK_KINDS)}")
        task: dict[str, Any] = {
            "id": task_id,
            "kind": kind,
            "title": str(raw.get("title") or "").strip() or task_id,
            "evidence": str(raw.get("evidence") or "").strip(),
        }
        if kind == "api":
            _validate_api_task(raw, task, feature, context, label, errors)
        elif kind == "analysis":
            depends_on = _string_list(raw.get("depends_on"))
            if not depends_on:
                errors.append(f"{label}: analysis tasks must list depends_on")
            else:
                missing = [d for d in depends_on if d not in seen]
                if missing:
                    errors.append(f"{label}: depends_on names tasks not defined before it: {missing}")
            task["depends_on"] = depends_on or []
            task["instruction"] = str(raw.get("instruction") or "").strip()
            if not task["instruction"]:
                errors.append(f"{label}: analysis tasks need an instruction")
        if task_id:
            seen.append(task_id)
        tasks.append(task)

    if tasks and not any(t["kind"] == "api" for t in tasks):
        errors.append("at least one task must call an endpoint")

    criteria = _string_list(plan.get("success_criteria"))
    if criteria is None:
        errors.append("success_criteria must be a list of strings")
    elif not criteria:
        errors.append("success_criteria needs at least one entry")
    limitations = _string_list(plan.get("limitations"))
    if limitations is None:
        errors.append("limitations must be a list of strings")

    if errors:
        raise ContractError(errors)
    return {
        "objective": objective,
        "tasks": tasks,
        "success_criteria": criteria,
        "limitations": limitations or [],
    }


def _validate_api_task(raw: dict[str, Any], task: dict[str, Any], feature: str,
                       context: dict[str, Any], label: str, errors: list[str]) -> None:
    path = str(raw.get("endpoint") or "").strip()
    entry = catalogue.endpoint(feature, path)
    if entry is None:
        allowed = [e["path"] for e in catalogue.endpoints(feature)]
        errors.append(f"{label}: endpoint {path!r} is not in the {feature} catalogue {allowed}")
        task["endpoint"], task["params"] = path, {}
        return
    params = raw.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errors.append(f"{label}: params must be an object")
        params = {}
    clean: dict[str, Any] = {}
    for name, value in params.items():
        if name not in entry["params"]:
            errors.append(f"{label}: parameter {name!r} is not declared for {path}; allowed {list(entry['params'])}")
            continue
        if name in CONTEXT_PARAMS:
            number = _as_int(value)
            if number is None:
                errors.append(f"{label}: {name} must be an integer")
                continue
            if name in context and int(context[name]) != number:
                errors.append(f"{label}: {name}={number} does not match the context ({context[name]})")
                continue
            clean[name] = number
        elif name == "limit":
            number = _as_int(value)
            if number is None or number < 1:
                errors.append(f"{label}: limit must be a positive integer")
                continue
            clean[name] = number
        else:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}: {name} must be a non-empty string")
                continue
            clean[name] = value.strip()
    for name in entry["required"]:
        if name not in clean:
            errors.append(f"{label}: {path} requires {name}")
    task["endpoint"], task["params"] = path, clean
