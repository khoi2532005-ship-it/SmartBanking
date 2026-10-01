"""Release 1 JSON API for the shared MCP and RAG servers."""

from __future__ import annotations

from flask import Blueprint, jsonify

from routes import json_object
from services import mcp_client, rag_client

agents_bp = Blueprint("agents", __name__)

ALLOWED_TOOLS = ("transactions_spending",)
DEFAULT_TOOL = "transactions_spending"


def _integration_error(exc: Exception):
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled)):
        return jsonify({"error": str(exc), "disabled": True}), 503
    if isinstance(exc, (mcp_client.MCPUnreachable, rag_client.RAGUnreachable)):
        return jsonify({"error": str(exc), "unreachable": True}), 503
    if isinstance(exc, mcp_client.MCPProtocolError):
        return jsonify({"error": str(exc)}), 502
    if isinstance(exc, rag_client.RAGError):
        body = {"error": str(exc)}
        for key in ("retrieval_summary", "evidence", "query"):
            if key in exc.payload:
                body[key] = exc.payload[key]
        return jsonify(body), exc.status if 400 <= exc.status < 600 else 502
    raise exc


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
