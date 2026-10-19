"""JSON API: Frontend -> this backend -> the shared MCP, RAG and Multi-Agent servers.

The frontend never talks to the shared servers directly; every request goes
through here. This is where the feature's own boundary lives: only known
read-only tools can be invoked, inputs are checked before they leave the
container, and a server that is down or disabled becomes one readable JSON
error rather than a stack trace.

    GET  /api/agents/status   every integration: enabled? reachable? which tools?
    GET  /api/mcp/tools       tools/list relayed from the shared MCP server
    POST /api/mcp/tool        {"tool"?, "arguments"?}  -> structured tool result
    POST /api/rag/query       {"query", "k"?}          -> grounded answer contract

Release 2, the shared Multi-Agent Server (Planner -> Worker -> Reviewer -> human):

    POST /api/multi-agent/workflows                  {"request", "customer_id"?, "month"?, "year"?} -> 202 summary
    GET  /api/multi-agent/workflows                  the most recent budgeting workflows (history)
    GET  /api/multi-agent/workflows/<id>             the whole workflow: stages, plan, result, review, decision, final response
    POST /api/multi-agent/workflows/<id>/decision    {"decision": accept|partially_accept|reject, "note"?, "reviewer"?}

Two boundaries apply to the Multi-Agent routes. This feature acts only on
its own workflows: another feature's id is a 404 here. And every POST must
carry the HX-Request or X-Requested-With header, which a cross-site form
cannot send, so no other website can start a workflow or decide one.

Status codes: 200 success (including a grounded "insufficient context"
answer, which is a valid response); 202 workflow started; 400 bad request;
409 the workflow is not in the state the call needs; 422 the MCP tool itself
returned isError; 502 protocol error; 503 integration disabled, server
unreachable, or the RAG server's LLM provider unavailable.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from routes import json_object
from services import mcp_client, multi_agent_client, rag_client

agents_bp = Blueprint("agents", __name__)

# The five read-only tools registered on the shared server. Anything else is
# refused here before a request leaves the container.
ALLOWED_TOOLS = (
    "budgeting_summary",
    "transactions_spending",
    "accounts_count",
    "loans_list",
    "fraud_alerts_count",
)
DEFAULT_TOOL = "budgeting_summary"


def _current_period() -> tuple[int, int]:
    today = date.today()
    return today.month, today.year


def _integration_error(exc: Exception):
    """One place that maps client exceptions to (json, status)."""
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled, multi_agent_client.MultiAgentDisabled)):
        return jsonify({"error": str(exc), "disabled": True}), 503
    if isinstance(exc, (mcp_client.MCPUnreachable, rag_client.RAGUnreachable, multi_agent_client.MultiAgentUnreachable)):
        return jsonify({"error": str(exc), "unreachable": True}), 503
    if isinstance(exc, mcp_client.MCPProtocolError):
        return jsonify({"error": str(exc)}), 502
    if isinstance(exc, multi_agent_client.MultiAgentError):
        # The server's own status and reason pass through (400, 404, 409, 413); a
        # token mismatch is configuration, so it is reported like an unreachable server.
        body = {"error": str(exc)}
        for key in ("state", "awaiting_decision", "options", "links"):
            if key in exc.payload:
                body[key] = exc.payload[key]
        if exc.status == 401:
            body["unreachable"] = True
            return jsonify(body), 503
        return jsonify(body), exc.status if 400 <= exc.status < 600 else 502
    if isinstance(exc, rag_client.RAGError):
        body = {"error": str(exc)}
        # A 503 from the RAG server means its LLM was unavailable; it still
        # tells us what it retrieved, which the UI can show.
        for key in ("retrieval_summary", "evidence", "query"):
            if key in exc.payload:
                body[key] = exc.payload[key]
        return jsonify(body), exc.status if 400 <= exc.status < 600 else 502
    raise exc


# ---------------------------------------------------------------------------

@agents_bp.get("/api/agents/status")
def agents_status():
    return jsonify({"mcp": mcp_client.status(), "rag": rag_client.status(), "multi_agent": multi_agent_client.status()})


@agents_bp.get("/api/mcp/tools")
def mcp_tools():
    try:
        tools = mcp_client.list_tools()
    except (mcp_client.MCPDisabled, mcp_client.MCPUnreachable, mcp_client.MCPProtocolError) as exc:
        return _integration_error(exc)
    return jsonify({
        "server": mcp_client.server_url(),
        "tool_count": len(tools),
        "tools": [
            {"name": t.name, "description": t.description,
             "required": t.input_schema.get("required", []),
             "properties": sorted((t.input_schema.get("properties") or {}).keys())}
            for t in tools
        ],
    })


@agents_bp.post("/api/mcp/tool")
def mcp_tool():
    data, error = json_object()
    if error:
        return error
    tool = str(data.get("tool") or DEFAULT_TOOL).strip()
    if tool not in ALLOWED_TOOLS:
        return jsonify({
            "error": f"tool {tool!r} is not one of the read-only tools this feature may call",
            "allowed_tools": list(ALLOWED_TOOLS),
        }), 400

    arguments = data.get("arguments")
    if arguments is None:
        # Convenience for this feature's own tool: build the arguments from
        # the same customer/period fields the rest of the API uses.
        month, year = _current_period()
        arguments = {
            "customer_id": data.get("customer_id", 1),
            "month": data.get("month") or month,
            "year": data.get("year") or year,
        } if tool in ("budgeting_summary", "transactions_spending") else {}
    if not isinstance(arguments, dict):
        return jsonify({"error": "arguments must be a JSON object"}), 400

    try:
        result = mcp_client.call_tool(tool, arguments)
    except (mcp_client.MCPDisabled, mcp_client.MCPUnreachable, mcp_client.MCPProtocolError) as exc:
        return _integration_error(exc)

    if result.is_error:
        return jsonify({
            "tool": tool, "arguments": arguments, "is_error": True,
            "error": result.text or "the tool returned an error without a message",
        }), 422

    return jsonify({
        "tool": tool, "arguments": arguments, "is_error": False,
        "server": mcp_client.server_url(),
        "result": result.structured if result.structured is not None else {"text": result.text},
    })


@agents_bp.post("/api/rag/query")
def rag_query():
    data, error = json_object()
    if error:
        return error
    question = str(data.get("query") or "").strip()
    if not question:
        return jsonify({"error": "query is required"}), 400
    if len(question) > rag_client.MAX_QUERY_CHARS:
        return jsonify({"error": f"query must be {rag_client.MAX_QUERY_CHARS} characters or fewer"}), 400
    k = data.get("k")
    try:
        k = int(k) if k not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "k must be an integer"}), 400

    try:
        answer = rag_client.query(question, k)
    except (rag_client.RAGDisabled, rag_client.RAGUnreachable, rag_client.RAGError) as exc:
        return _integration_error(exc)
    answer["server"] = rag_client.server_url()
    return jsonify(answer)


# ---------------------------------------------------------------------------
# Release 2: the shared Multi-Agent Server
# ---------------------------------------------------------------------------

_MA_ERRORS = (multi_agent_client.MultiAgentDisabled, multi_agent_client.MultiAgentUnreachable,
              multi_agent_client.MultiAgentError)
MAX_REVIEWER_CHARS = 60
HISTORY_LIMIT = 10
WORKFLOW_KEYS = ("workflow_id", "feature", "state", "request", "context", "created_at", "updated_at", "stages",
                 "revisions", "plan", "result", "review", "decision", "final_response", "error")


def same_origin_marker(headers) -> bool:
    """HTMX sends HX-Request on every call; scripts send X-Requested-With. A
    plain cross-site form cannot set either, which is what stops it."""
    return headers.get("HX-Request", "").lower() == "true" or bool(headers.get("X-Requested-With"))


def _same_origin_guard():
    if not same_origin_marker(request.headers):
        return jsonify({"error": "this route is for the budgeting panel: send the HX-Request or X-Requested-With header"}), 403
    return None


def _budgeting_only(record):
    """A workflow of another feature does not exist as far as this feature is concerned."""
    if not multi_agent_client.is_budgeting(record):
        return jsonify({"error": f"unknown budgeting workflow {record.get('workflow_id')!r}"}), 404
    return None


def _period_from(data):
    """customer_id, month and year from a JSON body, with the API's usual defaults."""
    month, year = _current_period()
    values = {"customer_id": data.get("customer_id", 1), "month": data.get("month") or month, "year": data.get("year") or year}
    clean = {}
    for key, value in values.items():
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            return None, (jsonify({"error": f"{key} must be an integer"}), 400)
        try:
            clean[key] = int(value)
        except (TypeError, ValueError):
            return None, (jsonify({"error": f"{key} must be an integer"}), 400)
    return clean, None


@agents_bp.post("/api/multi-agent/workflows")
def multi_agent_start():
    refused = _same_origin_guard()
    if refused:
        return refused
    data, error = json_object()
    if error:
        return error
    text = str(data.get("request") or "").strip()
    if not text:
        return jsonify({"error": "request is required"}), 400
    if len(text) > multi_agent_client.MAX_REQUEST_CHARS:
        return jsonify({"error": f"request must be {multi_agent_client.MAX_REQUEST_CHARS} characters or fewer"}), 400
    scope, error = _period_from(data)
    if error:
        return error
    try:
        summary = multi_agent_client.start(text, scope["customer_id"], scope["month"], scope["year"])
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    summary["server"] = multi_agent_client.server_url()
    return jsonify(summary), 202


@agents_bp.get("/api/multi-agent/workflows")
def multi_agent_history():
    """The most recent budgeting workflows, newest first, for the panel's history list."""
    try:
        listing = multi_agent_client.history()
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    mine = [w for w in listing if multi_agent_client.is_budgeting(w)][:HISTORY_LIMIT]
    return jsonify({"count": len(mine), "workflows": mine})


@agents_bp.get("/api/multi-agent/workflows/<workflow_id>")
def multi_agent_workflow(workflow_id):
    """The whole workflow, for polling and for the panel: the stages while it
    runs, then the plan, the Worker result and the review, and once the
    person has decided, the decision and the final response."""
    try:
        full = multi_agent_client.workflow(workflow_id)
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return _budgeting_only(full) or jsonify({key: full.get(key) for key in WORKFLOW_KEYS})


@agents_bp.post("/api/multi-agent/workflows/<workflow_id>/decision")
def multi_agent_decision(workflow_id):
    refused = _same_origin_guard()
    if refused:
        return refused
    data, error = json_object()
    if error:
        return error
    decision = str(data.get("decision") or "").strip()
    note = str(data.get("note") or "").strip()
    reviewer = str(data.get("reviewer") or "").strip()
    normalised = decision.lower().replace(" ", "_").replace("-", "_")
    if normalised not in multi_agent_client.DECISIONS:
        return jsonify({"error": f"decision must be one of {', '.join(multi_agent_client.DECISIONS)}",
                        "options": list(multi_agent_client.DECISIONS)}), 400
    if len(reviewer) > MAX_REVIEWER_CHARS:
        return jsonify({"error": f"reviewer must be {MAX_REVIEWER_CHARS} characters or fewer"}), 400
    if normalised == "partially_accept" and not note:
        return jsonify({"error": "partially_accept needs a note saying what to correct"}), 400
    if len(note) > multi_agent_client.MAX_NOTE_CHARS:
        return jsonify({"error": f"note must be {multi_agent_client.MAX_NOTE_CHARS} characters or fewer"}), 400
    try:
        multi_agent_client.check_workflow_id(workflow_id)        # the body is valid; now the server
        summary = multi_agent_client.workflow_status(workflow_id)
        refused = _budgeting_only(summary)
        if refused:
            return refused
        body = multi_agent_client.decide(workflow_id, decision, note, by=decided_by(reviewer))
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return jsonify(body)


def decided_by(reviewer: str) -> str:
    """Who decided, for the audit: this feature's panel, and the name the reviewer gave."""
    return f"budgeting-ui:{reviewer}" if reviewer else "budgeting-ui"
