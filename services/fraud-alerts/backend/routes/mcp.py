"""Release 1: the AI Mode tab reaches the shared MCP server through here.

    GET  /api/mcp/tools   the tools registered on the shared server (tools/list)
    POST /api/mcp/tool    {"customer_id"?, "status"?} -> fraud_alerts_count result

The frontend never talks to the MCP server itself. Inputs are checked here,
before anything leaves the container, so a typo is a 400 with a readable
message instead of the server's validation dump.
"""

from flask import Blueprint, jsonify, request

from services import mcp_client
from services.constants import ALERT_STATUSES
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable, failure
from services.validation import ValidationError, choice, positive_int

mcp_bp = Blueprint("mcp", __name__, url_prefix="/api/mcp")

SERVER_ERRORS = (ServerDisabled, ServerUnavailable, BadServerResponse)


@mcp_bp.get("/tools")
def list_tools():
    try:
        tools = mcp_client.list_tools()
    except SERVER_ERRORS as exc:
        body, status = failure(exc)
        return jsonify(body), status
    return jsonify({"server": mcp_client.server_url(), "tool_count": len(tools), "tools": tools})


@mcp_bp.post("/tool")
def call_fraud_alerts_count():
    # Every argument is optional, so an empty body counts all alerts.
    data = request.get_json(silent=True) if request.data else {}
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    tool = data.get("tool") or mcp_client.FRAUD_TOOL
    if tool != mcp_client.FRAUD_TOOL:
        return jsonify({"error": f"This feature calls only {mcp_client.FRAUD_TOOL}, not {tool!r}"}), 400

    try:
        customer_id = data.get("customer_id")
        customer_id = None if customer_id in (None, "") else positive_int(customer_id, "customer_id")
        status = data.get("status")
        status = None if status in (None, "") else choice(status, "status", ALERT_STATUSES)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        arguments, result = mcp_client.fraud_alerts_count(customer_id, status)
    except mcp_client.ToolFailed as exc:
        # Inputs were valid, so this is the tool failing upstream (e.g. it could
        # not reach this service's /api/alerts): a gateway error, not a bad request.
        return jsonify({"error": f"MCP tool {mcp_client.FRAUD_TOOL} failed: {exc}"}), 502
    except SERVER_ERRORS as exc:
        body, status_code = failure(exc)
        return jsonify(body), status_code

    return jsonify({
        "tool": mcp_client.FRAUD_TOOL,
        "arguments": arguments,
        "server": mcp_client.server_url(),
        "result": result,
    })
