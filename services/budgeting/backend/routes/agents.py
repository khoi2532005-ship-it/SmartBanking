"""Release 1 JSON API: Frontend -> this backend -> shared MCP server / shared RAG server.

The frontend never talks to the shared servers directly; every MCP and RAG
request goes through here. This is where the feature's own boundary lives:
only known read-only tools can be invoked, inputs are checked before they
leave the container, and a server that is down or disabled becomes one
readable JSON error rather than a stack trace.

    GET  /api/agents/status   both integrations: enabled? reachable? which tools?
    GET  /api/mcp/tools       tools/list relayed from the shared MCP server
    POST /api/mcp/tool        {"tool"?, "arguments"?}  -> structured tool result
    POST /api/rag/query       {"query", "k"?}          -> grounded answer contract

Status codes: 200 success (including a grounded "insufficient context"
answer, which is a valid response); 400 bad request; 422 the MCP tool itself
returned isError; 502 protocol error; 503 integration disabled, server
unreachable, or the RAG server's LLM provider unavailable.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from services import mcp_client, rag_client

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
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled)):
        return jsonify({"error": str(exc), "disabled": True}), 503
    if isinstance(exc, (mcp_client.MCPUnreachable, rag_client.RAGUnreachable)):
        return jsonify({"error": str(exc), "unreachable": True}), 503
    if isinstance(exc, mcp_client.MCPProtocolError):
        return jsonify({"error": str(exc)}), 502
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
    return jsonify({"mcp": mcp_client.status(), "rag": rag_client.status()})


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
    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
    question = str(data.get("query") or "").strip()
    if not question:
        return jsonify({"error": "query is required"}), 400
    if len(question) > 1000:
        return jsonify({"error": "query must be 1000 characters or fewer"}), 400
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
