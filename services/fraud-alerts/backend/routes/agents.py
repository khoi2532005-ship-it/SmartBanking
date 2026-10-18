"""Release 2: the AI Mode tab runs Multi-Agent workflows through here.

    POST /api/agents/workflow               {"task", "customer_id"} -> 202 summary
    GET  /api/agents/workflow/<id>          plan, Worker result, review, decision, final response
    POST /api/agents/workflow/<id>/review   {"decision": accept|partially_accept|reject, "note"?, "reviewer"?}
    GET  /api/agents/workflows              this feature's workflows, newest first

The frontend never talks to the Multi-Agent Server itself. Ids and bodies are
checked here, before anything leaves the container, so only a workflow id is
ever placed in a server URL and a bad decision is a 400 with a readable
message instead of a round trip. The AI Mode tab is the analyst's review desk,
so it gets the full record, including the Worker's answer before release.
"""

from flask import Blueprint, jsonify, request

from services import multi_agent_client
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable, failure
from services.validation import ValidationError, validate_review, validate_workflow_start, workflow_id as checked_id

agents_bp = Blueprint("agents", __name__, url_prefix="/api/agents")

CALL_ERRORS = (ValidationError, multi_agent_client.WorkflowRefused, ServerDisabled, ServerUnavailable, BadServerResponse)
RECORD_FIELDS = ("workflow_id", "feature", "state", "request", "context", "created_at", "updated_at", "stages",
                 "revisions", "plan", "result", "review", "decision", "final_response", "error")


def _refused(exc):
    """(JSON body, status) for a call that did not go through."""
    if isinstance(exc, ValidationError):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, multi_agent_client.WorkflowRefused):
        # The server's own status and reason pass through: 404 unknown
        # workflow, 409 already decided (with the state it is in now).
        body = {"error": str(exc)}
        if "state" in exc.payload:
            body["state"] = exc.payload["state"]
        return jsonify(body), exc.status if 400 <= exc.status < 500 else 502
    body, status = failure(exc)
    return jsonify(body), status


@agents_bp.post("/workflow")
def start_workflow():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        task, customer_id = validate_workflow_start(data)
        summary = multi_agent_client.start(task, customer_id)
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({**summary, "server": multi_agent_client.server_url()}), 202


@agents_bp.get("/workflow/<workflow_id>")
def get_workflow(workflow_id):
    try:
        record = multi_agent_client.workflow(checked_id(workflow_id))
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({field: record.get(field) for field in RECORD_FIELDS})


@agents_bp.post("/workflow/<workflow_id>/review")
def review_workflow(workflow_id):
    try:
        workflow_id = checked_id(workflow_id)
    except ValidationError as exc:
        return _refused(exc)
    # A JSON body is also what keeps a cross-site form out: such a form can only
    # send text/plain or form-encoded bodies, which never parse here.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    try:
        decision, note, reviewer = validate_review(data)
        decided = multi_agent_client.review(workflow_id, decision, note, reviewer)
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify(decided)


@agents_bp.get("/workflows")
def list_workflows():
    try:
        workflows = multi_agent_client.history()
    except CALL_ERRORS as exc:
        return _refused(exc)
    return jsonify({"count": len(workflows), "workflows": workflows})
