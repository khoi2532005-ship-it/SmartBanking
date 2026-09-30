"""Release 1: the AI Mode tab reaches the shared MCP server through here.

    GET  /api/mcp/tools   the tools registered on the shared server (tools/list)
    POST /api/mcp/tool    {"customer_id"?} -> accounts_count result

The frontend never talks to the MCP server itself. Inputs are checked here,
before anything leaves the container, so a typo is a 400 with a readable
message instead of the server's validation dump.
"""

from flask import Blueprint, jsonify, request

from services import mcp_client
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable, failure

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
def call_accounts_count():
    # customer_id is optional, so an empty body counts across all customers.
    data = request.get_json(silent=True) if request.data else {}
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    tool = data.get("tool") or mcp_client.ACCOUNTS_TOOL
    if tool != mcp_client.ACCOUNTS_TOOL:
        return jsonify({"error": f"This feature calls only {mcp_client.ACCOUNTS_TOOL}, not {tool!r}"}), 400

    customer_id = data.get("customer_id")
    if customer_id not in (None, ""):
        try:
            customer_id = int(customer_id)
        except (TypeError, ValueError):
            return jsonify({"error": "customer_id must be a positive integer"}), 400
        if customer_id < 1:
            return jsonify({"error": "customer_id must be a positive integer"}), 400
    else:
        customer_id = None

    try:
        arguments, result = mcp_client.accounts_count(customer_id)
    except mcp_client.ToolFailed as exc:
        # The input was valid, so this is the tool failing upstream (e.g. it
        # could not reach this service's /api/accounts): a gateway error.
        return jsonify({"error": f"MCP tool {mcp_client.ACCOUNTS_TOOL} failed: {exc}"}), 502
    except SERVER_ERRORS as exc:
        body, status_code = failure(exc)
        return jsonify(body), status_code

    return jsonify({
        "tool": mcp_client.ACCOUNTS_TOOL,
        "arguments": arguments,
        "server": mcp_client.server_url(),
        "result": result,
    })
