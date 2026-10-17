"""Coordination metrics (Lecture 10), computed from the two audit files alone.

Nothing here reads server memory: the same numbers come out of a copy of
workflow_history.jsonl and coordination_audit.jsonl, which is what makes them
evidence. Rates are 0.0 to 1.0; times are seconds.

    plan_acceptance_rate      plans the contract accepted at the first attempt
    worker_completion_rate    worker stages that completed (incl. fallback)
    handoff_success_rate      stages after the planner that began with a handoff record
    reviewer_defect_yield     defects reported per review
    rework_ratio              revisions requested per workflow
    escalation_rate           workflows escalated to the human without an accept verdict
    fallback_rate             model stages answered by a fallback
    human_acceptance_rate     accept or partially accept, of all decisions
    stage_seconds             average duration per role
    end_to_end_seconds        average request -> human gate, and request -> decision
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

MODEL_ROLES = ("planner", "worker", "reviewer")


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _seconds(start: str | None, end: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def compute(history: list[dict[str, Any]], coordination: list[dict[str, Any]]) -> dict[str, Any]:
    workflows = {r["workflow_id"] for r in history} | {r["workflow_id"] for r in coordination}
    events = Counter(r["event"] for r in history)
    decisions = Counter(r["decision"] for r in coordination)

    created = {r["workflow_id"]: r["ts"] for r in history if r["event"] == "workflow_created"}
    gated = {r["workflow_id"]: r["ts"] for r in history
             if r["event"] == "state_changed" and r["detail"].get("to") == "awaiting_human_review"}
    completed = {r["workflow_id"]: r["ts"] for r in history if r["event"] == "workflow_completed"}
    final_state = {}
    for r in history:
        if r["event"] == "state_changed":
            final_state[r["workflow_id"]] = r["detail"].get("to")

    stage_started = Counter(r["role"] for r in history if r["event"] == "stage_started")
    stage_done = Counter(r["role"] for r in history
                         if r["event"] == "stage_completed"
                         or (r["event"] == "stage_timed_out" and r["detail"].get("fallback")))
    durations: dict[str, list[float]] = defaultdict(list)
    for r in history:
        if r["event"] in ("stage_completed", "stage_timed_out") and r["detail"].get("duration_seconds") is not None:
            durations[r["role"]].append(float(r["detail"]["duration_seconds"]))

    plans_first_try = sum(1 for r in coordination if r["decision"] == "plan_accepted"
                          and r["detail"].get("accepted_first_try"))
    plans_total = decisions["plan_accepted"] + sum(
        1 for r in coordination if r["decision"] == "fallback_applied" and r["detail"].get("stage") == "planner")
    reviews = [r for r in coordination if r["decision"] == "verdict_recorded"]
    defects = sum(int(r["detail"].get("defects", 0)) for r in reviews)
    model_stages = sum(stage_done[role] for role in MODEL_ROLES)
    fallbacks = sum(1 for r in coordination if r["decision"] == "fallback_applied")
    stages_after_planner = sum(stage_started[role] for role in ("worker", "reviewer", "human"))
    human = Counter(r["detail"].get("decision") for r in coordination if r["decision"] == "human_decision")
    decided = sum(human.values())

    return {
        "workflows": {
            "total": len(workflows),
            "by_final_state": dict(Counter(final_state.values())),
            "decided": decided,
            "failed": sum(1 for s in final_state.values() if s == "failed"),
        },
        "plan_acceptance_rate": _rate(plans_first_try, plans_total),
        "worker_completion_rate": _rate(stage_done["worker"], stage_started["worker"]),
        "handoff_success_rate": _rate(min(decisions["handoff"], stages_after_planner), stages_after_planner),
        "reviewer_defect_yield": _rate(defects, len(reviews)),
        "rework_ratio": _rate(decisions["revision_requested"], len(workflows)),
        "escalation_rate": _rate(decisions["escalated_to_human"], len(workflows)),
        "fallback_rate": _rate(fallbacks, model_stages),
        "human_acceptance_rate": _rate(human["accept"] + human["partially_accept"], decided),
        "human_decisions": dict(human),
        "stage_seconds": {role: _avg(durations[role]) for role in (*MODEL_ROLES, "human") if durations[role]},
        "end_to_end_seconds": {
            "to_human_gate": _avg([s for s in (_seconds(created.get(w), gated.get(w)) for w in gated) if s is not None]),
            "to_decision": _avg([s for s in (_seconds(created.get(w), completed.get(w)) for w in completed) if s is not None]),
        },
        "counts": {
            "history_records": len(history),
            "coordination_records": len(coordination),
            "stages_started": dict(stage_started),
            "stages_finished": dict(stage_done),
            "handoffs": decisions["handoff"],
            "handoff_anomalies": max(0, decisions["handoff"] - stages_after_planner),
            "contract_rejections": decisions["plan_rejected"] + decisions["result_rejected"] + decisions["review_rejected"],
            "revisions_requested": decisions["revision_requested"],
            "fallbacks": fallbacks,
            "escalations": decisions["escalated_to_human"],
            "timeouts": events["stage_timed_out"],
        },
    }
