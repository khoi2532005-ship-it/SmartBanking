"""Release 2: the Multi-Agent tab runs Planner -> Worker -> Reviewer workflows
through this loans blueprint, which fronts the shared Multi-Agent Server.

    POST /api/multi-agent/workflow                     {"user_request", "customer_id"?} -> 202 summary
    GET  /api/multi-agent/workflow/status?id=<wf_id>   one workflow's compact view; no id -> the newest loans workflow
    GET  /api/multi-agent/workflow/<id>                plan, Worker result, review, decision, final response
    POST /api/multi-agent/workflow/<id>/review         {"decision": accept|partially_accept|reject, "note"?, "reviewer"?}
    GET  /api/multi-agent/workflow/<id>/response       the final response; 409 until the decision is posted
    GET  /api/multi-agent/workflows                    this feature's workflows, newest first
    GET  /api/multi-agent/metrics                      audit and workflow counts for this feature
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from services import multi_agent_client as ma

multi_agent_bp = Blueprint("multi_agent", __name__)

MAX_REVIEWER_CHARS = 60
CALL_ERRORS = (ma.WorkflowRefused, ma.MultiAgentDisabled, ma.MultiAgentUnreachable, ma.BadServerResponse)
RECORD_FIELDS = ("workflow_id", "feature", "state", "request", "context", "created_at", "updated_at",
                 "stages", "revisions", "plan", "result", "review", "decision", "final_response", "error")


def _text(value) -> str:
    """Text a person typed: only a real string, stripped, empty allowed."""
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value):
    """The customer a workflow is about; None when the value cannot work."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def _refused(exc: Exception):
    """(JSON body, status) for a call that did not go through."""
    if isinstance(exc, ma.MultiAgentDisabled):
        return jsonify({"error": str(exc), "disabled": True}), 503
    if isinstance(exc, ma.MultiAgentUnreachable):
        return jsonify({"error": str(exc), "unreachable": True}), 503
    if isinstance(exc, ma.BadServerResponse):
        return jsonify({"error": str(exc)}), 502
    body = {"error": str(exc)}
    if "state" in exc.payload:
        body["state"] = exc.payload["state"]
    return jsonify(body), exc.status if 400 <= exc.status < 500 else 502


@multi_agent_bp.post("/api/multi-agent/workflow")
def start_workflow():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    task = _text(data.get("user_request")) or _text(data.get("request")) or _text(data.get("task"))
    if not task:
        return jsonify({"error": "user_request is required"}), 400
    if len(task) > ma.MAX_REQUEST_CHARS:
        return jsonify({"error": f"user_request must be {ma.MAX_REQUEST_CHARS} characters or fewer"}), 400
    customer_id = data.get("customer_id", 1)      # the demo customer, as the rest of the API defaults
    customer_id = _positive_int(customer_id)
    if customer_id is None:
        return jsonify({"error": "customer_id must be a positive integer"}), 400
    try:
        summary = ma.start(task, customer_id)
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({**summary, "server": ma.server_url()}), 202


@multi_agent_bp.get("/api/multi-agent/workflow/status")
def workflow_status():
    """One loans workflow's compact view. No id means the newest loans
    workflow, which is what the tab's Get Workflow Status button wants."""
    try:
        asked = _text(request.args.get("id"))
        if asked:
            summary = ma.workflow_status(ma.check_workflow_id(asked))
        else:
            history = ma.history()
            if not history:
                return jsonify({"error": "no loans workflows yet: start one from this tab"}), 404
            summary = ma.workflow_status(ma.check_workflow_id(history[0]["workflow_id"]))
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify(summary)


@multi_agent_bp.get("/api/multi-agent/metrics")
def workflow_metrics():
    try:
        metrics = ma.audit_metrics()
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify(metrics)


@multi_agent_bp.get("/api/multi-agent/workflow/<workflow_id>")
def get_workflow(workflow_id):
    try:
        record = ma.workflow(ma.check_workflow_id(workflow_id))
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({field: record.get(field) for field in RECORD_FIELDS})


@multi_agent_bp.post("/api/multi-agent/workflow/<workflow_id>/review")
def review_workflow(workflow_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    decision = _text(data.get("decision"))
    note = _text(data.get("note"))
    reviewer = _text(data.get("reviewer"))
    if len(reviewer) > MAX_REVIEWER_CHARS:
        return jsonify({"error": f"reviewer must be {MAX_REVIEWER_CHARS} characters or fewer"}), 400
    try:
        decided = ma.decide(ma.check_workflow_id(workflow_id), decision, note, reviewer)
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify(decided)


@multi_agent_bp.get("/api/multi-agent/workflow/<workflow_id>/response")
def workflow_response(workflow_id):
    """The final response; 409 with the current state while a decision is pending."""
    try:
        final = ma.response(ma.check_workflow_id(workflow_id))
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify(final)


@multi_agent_bp.get("/api/multi-agent/workflows")
def list_workflows():
    try:
        workflows = ma.history()
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({"count": len(workflows), "workflows": workflows})
