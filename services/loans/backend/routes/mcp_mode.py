"""MCP Mode routes for Loans & Credit (Release 1 integration).

Mirror of the enrolment-app MCP tab: the frontend posts an MCP tool request to
the feature backend with an X-MCP-Mode header; this blueprint applies the same
gate (MCP_ENABLED env var AND the header) and then runs the tool against the
shared MCP server instead of re-implementing the tool locally. Because the
shared server's tools are read-only and call each feature's existing API, the
frontend gets exactly what `python -m mcp_server.validate` tests.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from services import mcp_client

mcp_bp = Blueprint("mcp_mode", __name__)

TOOLS = [
    {
        "name": "loans_list",
        "description": "Loans held by one customer, with type, requested amount and status.",
        "parameters": [{"name": "customer_id", "required": True, "type": "int"},
                       {"name": "status", "required": False, "type": "str"}],
    },
]


def mcp_mode_is_enabled(req) -> bool:
    enabled = os.getenv("MCP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return False
    mode_header = req.headers.get("X-MCP-Mode", "on").strip().lower()
    return mode_header in ("1", "true", "yes", "on")


def mcp_disabled_response():
    return jsonify({"status": "error", "error": "MCP Mode is disabled."}), 403


@mcp_bp.get("/api/mcp/tools")
def mcp_tools():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()
    return jsonify({"status": "ok", "tools": TOOLS})


@mcp_bp.post("/api/mcp/loans-list")
def mcp_loans_list():
    if not mcp_mode_is_enabled(request):
        return mcp_disabled_response()

    data = request.get_json(silent=True) or request.form
    if not isinstance(data, dict):
        return jsonify({"status": "error", "error": "JSON body required"}), 400

    try:
        customer_id = int(data.get("customer_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "error": "customer_id must be a positive integer."}), 400
    if customer_id < 1:
        return jsonify({"status": "error", "error": "customer_id must be a positive integer."}), 400

    arguments = {"customer_id": customer_id}
    status = str(data.get("status") or "").strip().upper()
    if status:
        arguments["status"] = status

    try:
        result = mcp_client.call_tool("loans_list", arguments)
    except mcp_client.MCPUnavailable as exc:
        return jsonify({"status": "error", "error": str(exc)}), 503

    if result["is_error"]:
        return (
            jsonify({"status": "error", "tool": "loans_list", "error": result["text"] or "MCP tool failed."}),
            502,
        )

    return jsonify({"status": "ok", "tool": result["tool"], "result": result["structured"]})