"""Handoff contracts (Lecture 10): what one role must hand the next.

A contract is checked by code, not by another model. The Planner's plan is
validated against the endpoint catalogue and the workflow context before the
Worker ever sees it, so a plan that names an unknown endpoint, an undeclared
parameter or another customer is rejected with the reasons, and the model
gets one chance to correct it. The Worker's result is checked the same way:
every finding must name its analysis task and the api tasks it rests on, and
every figure in it must appear in the collected evidence. The Reviewer's
verdict is bound by a completion gate: "accept" needs every criterion met and
no high-severity defect, otherwise the contract demands "revise" with notes.
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


# ---------------------------------------------------------------- Worker result

MAX_STATEMENT_CHARS = 600
MAX_ANSWER_CHARS = 2000
# Small whole numbers (months, ranks, "2 of 7 budgets") are not checked; dollar
# amounts, percentages and counts above this must come from the evidence.
SMALL_NUMBER = 12
_NUMBER = re.compile(r"(?<![A-Za-z\d.])-?\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_in_text(text: str) -> list[tuple[float, int]]:
    """Every number written in `text` as (value, decimals written)."""
    found = []
    for match in _NUMBER.finditer(text or ""):
        raw = match.group(0).replace("$", "").replace(",", "").rstrip("%")
        if not raw or raw == "-":
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        found.append((value, decimals))
    return found


def numbers_in_data(data: Any, into: set[float] | None = None) -> set[float]:
    """Every numeric value inside nested JSON data (numbers and numeric strings)."""
    into = set() if into is None else into
    if isinstance(data, bool):
        return into
    if isinstance(data, (int, float)):
        into.add(float(data))
    elif isinstance(data, str):
        stripped = data.strip().replace(",", "")
        try:
            into.add(float(stripped))
        except ValueError:
            pass
    elif isinstance(data, dict):
        for value in data.values():
            numbers_in_data(value, into)
    elif isinstance(data, (list, tuple)):
        for value in data:
            numbers_in_data(value, into)
    return into


def ungrounded_numbers(text: str, allowed: set[float]) -> list[str]:
    """Numbers written in `text` that no evidence value equals or rounds to."""
    missing = []
    for value, decimals in numbers_in_text(text):
        if decimals == 0 and abs(value) <= SMALL_NUMBER:
            continue
        if any(abs(candidate - value) < 1e-9 or abs(round(candidate, decimals) - value) < 1e-9
               for candidate in allowed):
            continue
        written = f"{value:.{decimals}f}" if decimals else f"{int(value)}"
        if written not in missing:
            missing.append(written)
    return missing


def validate_result(result: dict[str, Any], plan: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the normalised Worker result, or raise ContractError listing every problem."""
    errors: list[str] = []
    analysis_ids = [t["id"] for t in plan.get("tasks", []) if t["kind"] == "analysis"]
    ok_ids = [r["task_id"] for r in evidence if r["status"] == "ok"]
    failed_ids = [r["task_id"] for r in evidence if r["status"] != "ok"]
    allowed = set()
    for record in evidence:
        if record["status"] == "ok":
            numbers_in_data(record["summary"], allowed)
            numbers_in_data(record["params"], allowed)

    raw_findings = result.get("findings")
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, list):
        errors.append("findings must be a list")
        raw_findings = []
    findings: list[dict[str, Any]] = []
    covered: set[str] = set()
    for index, raw in enumerate(raw_findings, start=1):
        label = f"finding {index}"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be an object")
            continue
        task_id = str(raw.get("task_id") or "").strip()
        if task_id not in analysis_ids:
            errors.append(f"{label}: task_id {task_id!r} is not an analysis task in the plan {analysis_ids}")
        statement = str(raw.get("statement") or "").strip()
        if not statement:
            errors.append(f"{label}: statement is required")
        elif len(statement) > MAX_STATEMENT_CHARS:
            errors.append(f"{label}: statement must be {MAX_STATEMENT_CHARS} characters or fewer")
        refs = _string_list(raw.get("evidence"))
        if not refs:
            errors.append(f"{label}: evidence must list at least one api task id")
            refs = []
        for ref in refs:
            if ref in failed_ids:
                errors.append(f"{label}: evidence task {ref} did not succeed, so it cannot support a finding")
            elif ref not in ok_ids:
                errors.append(f"{label}: evidence task {ref!r} is not an api task of the plan {ok_ids}")
        for number in ungrounded_numbers(statement, allowed):
            errors.append(f"{label}: the number {number} is not in the evidence; copy figures exactly from it or leave them out")
        covered.add(task_id)
        findings.append({"task_id": task_id, "statement": statement, "evidence": refs})

    for task_id in analysis_ids:
        if task_id not in covered:
            errors.append(f"analysis task {task_id} has no finding")

    answer = str(result.get("answer") or "").strip()
    if not answer:
        errors.append("answer is required")
    elif len(answer) > MAX_ANSWER_CHARS:
        errors.append(f"answer must be {MAX_ANSWER_CHARS} characters or fewer")
    for number in ungrounded_numbers(answer, allowed):
        errors.append(f"answer: the number {number} is not in the evidence; copy figures exactly from it or leave them out")

    gaps = _string_list(result.get("gaps"))
    if gaps is None:
        errors.append("gaps must be a list of strings")

    if errors:
        raise ContractError(errors)
    return {"findings": findings, "answer": answer, "gaps": gaps or []}


# ---------------------------------------------------------------- Reviewer verdict

VERDICTS = ("accept", "revise")
SEVERITIES = ("high", "medium", "low")
MAX_NOTE_CHARS = 600


def validate_review(review: dict[str, Any], plan: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the normalised review, or raise ContractError listing every problem.

    The completion gate lives here: a verdict of accept with an unmet criterion
    or a high-severity defect is a contract violation, not a judgement call.
    """
    errors: list[str] = []
    criteria_count = len(plan.get("success_criteria", []))
    allowed = set()
    for record in evidence:
        if record["status"] == "ok":
            numbers_in_data(record["summary"], allowed)
            numbers_in_data(record["params"], allowed)

    verdict = str(review.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        errors.append(f"verdict must be one of {list(VERDICTS)}")

    summary = str(review.get("summary") or "").strip()
    if not summary:
        errors.append("summary is required")
    elif len(summary) > MAX_NOTE_CHARS:
        errors.append(f"summary must be {MAX_NOTE_CHARS} characters or fewer")
    for number in ungrounded_numbers(summary, allowed):
        errors.append(f"summary: the number {number} is not in the evidence; quote figures exactly or leave them out")

    raw_criteria = review.get("criteria")
    if not isinstance(raw_criteria, list):
        errors.append("criteria must be a list with one entry per success criterion")
        raw_criteria = []
    criteria: list[dict[str, Any]] = []
    seen: set[int] = set()
    unmet: list[int] = []
    for position, raw in enumerate(raw_criteria, start=1):
        label = f"criteria entry {position}"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be an object")
            continue
        index = _as_int(raw.get("index"))
        if index is None or not 1 <= index <= criteria_count:
            errors.append(f"{label}: index must be between 1 and {criteria_count}")
            continue
        if index in seen:
            errors.append(f"{label}: criterion {index} is judged twice")
            continue
        seen.add(index)
        met = raw.get("met")
        if not isinstance(met, bool):
            errors.append(f"{label}: met must be true or false")
            met = False
        if not met:
            unmet.append(index)
        note = str(raw.get("note") or "").strip()[:MAX_NOTE_CHARS]
        for number in ungrounded_numbers(note, allowed):
            errors.append(f"{label}: the number {number} is not in the evidence")
        criteria.append({"index": index, "met": met, "note": note})
    missing = [i for i in range(1, criteria_count + 1) if i not in seen]
    if missing:
        errors.append(f"criteria must judge every success criterion; missing {missing}")
    criteria.sort(key=lambda c: c["index"])

    raw_defects = review.get("defects")
    if raw_defects is None:
        raw_defects = []
    if not isinstance(raw_defects, list):
        errors.append("defects must be a list")
        raw_defects = []
    defects: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_defects, start=1):
        label = f"defect {position}"
        if not isinstance(raw, dict):
            errors.append(f"{label} must be an object")
            continue
        severity = str(raw.get("severity") or "").strip().lower()
        if severity not in SEVERITIES:
            errors.append(f"{label}: severity must be one of {list(SEVERITIES)}")
        note = str(raw.get("note") or "").strip()
        if not note:
            errors.append(f"{label}: note is required")
        for number in ungrounded_numbers(note, allowed):
            errors.append(f"{label}: the number {number} is not in the evidence")
        defects.append({"severity": severity, "about": str(raw.get("about") or "").strip(), "note": note[:MAX_NOTE_CHARS]})

    risks = _string_list(review.get("risks"))
    if risks is None:
        errors.append("risks must be a list of strings")
        risks = []
    notes = _string_list(review.get("revision_notes"))
    if notes is None:
        errors.append("revision_notes must be a list of strings")
        notes = []
    for text in risks + notes:
        for number in ungrounded_numbers(text, allowed):
            errors.append(f"the number {number} is not in the evidence: {text[:60]!r}")

    high = [d for d in defects if d["severity"] == "high"]
    if verdict == "accept":
        if unmet:
            errors.append(f"verdict accept is not allowed while criteria {unmet} are unmet; return revise with revision_notes")
        if high:
            errors.append("verdict accept is not allowed with a high-severity defect; return revise with revision_notes")
        notes = []
    elif verdict == "revise" and not notes:
        errors.append("verdict revise requires at least one revision note the Worker can act on")

    if errors:
        raise ContractError(errors)
    return {"verdict": verdict, "summary": summary, "criteria": criteria, "defects": defects,
            "risks": risks, "revision_notes": notes}
