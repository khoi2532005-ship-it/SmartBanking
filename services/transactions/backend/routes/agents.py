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
    GET  /api/multi-agent/workflows/<id>             summary, for polling (transactions workflows only)
    GET  /api/multi-agent/workflows/<id>/review-panel plan, result and review: operator only
    POST /api/multi-agent/workflows/<id>/decision    {"decision": accept|partially_accept|reject, "note"?, "reviewer"?}: operator only
    GET  /api/multi-agent/workflows/<id>/response    the approved answer only; 409 until the decision is made
    GET  /api/multi-agent/pending                    transactions workflows waiting for a decision: operator only
"""

from __future__ import annotations

import hmac
import os
from datetime import date

from flask import Blueprint, jsonify, request

from routes import json_object
from services import mcp_client, multi_agent_client, rag_client

agents_bp = Blueprint("agents", __name__)

ALLOWED_TOOLS = ("transactions_spending",)
DEFAULT_TOOL = "transactions_spending"


def _current_period() -> tuple[int, int]:
    today = date.today()
    return today.month, today.year


def _integration_error(exc: Exception):
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled, multi_agent_client.MultiAgentDisabled)):
        return jsonify({"error": str(exc), "disabled": True}), 503
    if isinstance(exc, (mcp_client.MCPUnreachable, rag_client.RAGUnreachable, multi_agent_client.MultiAgentUnreachable)):
        return jsonify({"error": str(exc), "unreachable": True}), 503
    if isinstance(exc, mcp_client.MCPProtocolError):
        return jsonify({"error": str(exc)}), 502
    if isinstance(exc, multi_agent_client.MultiAgentError):
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
        for key in ("retrieval_summary", "evidence", "query"):
            if key in exc.payload:
                body[key] = exc.payload[key]
        return jsonify(body), exc.status if 400 <= exc.status < 600 else 502
    raise exc


@agents_bp.get("/api/agents/status")
def agents_status():
    multi_agent = multi_agent_client.status()
    multi_agent["reviewer_token_required"] = bool(reviewer_token())
    return jsonify({"mcp": mcp_client.status(), "rag": rag_client.status(), "multi_agent": multi_agent})


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
        arguments = {
            "customer_id": data.get("customer_id", 1),
            "month": data.get("month") or 1,
            "year": data.get("year") or 2026,
        }
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


def reviewer_token() -> str:
    return os.getenv("TRANSACTIONS_REVIEWER_TOKEN", "").strip()


def same_origin_marker(headers) -> bool:
    return headers.get("HX-Request", "").lower() == "true" or bool(headers.get("X-Requested-With"))


def operator_check(headers, *, state_changing: bool):
    if state_changing and not same_origin_marker(headers):
        return ("this route is for the transactions panel: send the HX-Request or X-Requested-With header", 403)
    token = reviewer_token()
    if token:
        presented = headers.get("X-Reviewer-Token", "").encode("utf-8", "surrogateescape")
        if not hmac.compare_digest(presented, token.encode("utf-8")):
            return ("a reviewer token is required: send X-Reviewer-Token (TRANSACTIONS_REVIEWER_TOKEN)", 403)
    return None


def _operator_guard(*, state_changing: bool):
    refused = operator_check(request.headers, state_changing=state_changing)
    if refused:
        reason, status = refused
        return jsonify({"error": reason, "operator_route": True}), status
    return None


def _transactions_only(record):
    if not multi_agent_client.is_transactions(record):
        return jsonify({"error": f"unknown transactions workflow {record.get('workflow_id')!r}"}), 404
    return None


def _period_from(data):
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
    if not same_origin_marker(request.headers):
        return jsonify({"error": "send the HX-Request or X-Requested-With header to start a workflow"}), 403
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


@agents_bp.get("/api/multi-agent/workflows/<workflow_id>")
def multi_agent_workflow_status(workflow_id):
    try:
        summary = multi_agent_client.workflow_status(workflow_id)
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return _transactions_only(summary) or jsonify(summary)


@agents_bp.get("/api/multi-agent/workflows/<workflow_id>/review-panel")
def multi_agent_review_panel(workflow_id):
    refused = _operator_guard(state_changing=False)
    if refused:
        return refused
    try:
        full = multi_agent_client.workflow(workflow_id)
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return _transactions_only(full) or jsonify({key: full.get(key) for key in (
        "workflow_id", "state", "request", "context", "stages", "revisions", "plan", "result", "review",
        "decision", "final_response", "error")})


@agents_bp.post("/api/multi-agent/workflows/<workflow_id>/decision")
def multi_agent_decision(workflow_id):
    refused = _operator_guard(state_changing=True)
    if refused:
        return refused
    data, error = json_object()
    if error:
        return error
    decision = str(data.get("decision") or "").strip()
    note = str(data.get("note") or "").strip()
    reviewer = str(data.get("reviewer") or "").strip()
    if decision.lower().replace(" ", "_").replace("-", "_") not in multi_agent_client.DECISIONS:
        return jsonify({"error": f"decision must be one of {', '.join(multi_agent_client.DECISIONS)}",
                        "options": list(multi_agent_client.DECISIONS)}), 400
    if len(reviewer) > MAX_REVIEWER_CHARS:
        return jsonify({"error": f"reviewer must be {MAX_REVIEWER_CHARS} characters or fewer"}), 400
    normalised = decision.lower().replace(" ", "_").replace("-", "_")
    if normalised == "partially_accept" and not note:
        return jsonify({"error": "partially_accept needs a note saying what to correct"}), 400
    if len(note) > multi_agent_client.MAX_NOTE_CHARS:
        return jsonify({"error": f"note must be {multi_agent_client.MAX_NOTE_CHARS} characters or fewer"}), 400
    try:
        multi_agent_client.check_workflow_id(workflow_id)
        summary = multi_agent_client.workflow_status(workflow_id)
        refused = _transactions_only(summary)
        if refused:
            return refused
        body = multi_agent_client.decide(workflow_id, decision, note, by=decided_by(reviewer))
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return jsonify(body)


def decided_by(reviewer: str) -> str:
    return f"transactions-ui:{reviewer}" if reviewer else "transactions-ui"


@agents_bp.get("/api/multi-agent/workflows/<workflow_id>/response")
def multi_agent_response(workflow_id):
    try:
        final = multi_agent_client.response(workflow_id)
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    return _transactions_only(final) or jsonify(multi_agent_client.customer_view(final))


@agents_bp.get("/api/multi-agent/pending")
def multi_agent_pending():
    refused = _operator_guard(state_changing=False)
    if refused:
        return refused
    try:
        listing = multi_agent_client.pending()
    except _MA_ERRORS as exc:
        return _integration_error(exc)
    mine = [w for w in listing.get("workflows") or [] if multi_agent_client.is_transactions(w)]
    return jsonify({**listing, "count": len(mine), "workflows": mine})
