"""Client for the shared MCP server (Release 1).

The server (python -m mcp_server.server on the host) speaks streamable HTTP
statelessly with JSON replies: one MCP request is one POST carrying a JSON-RPC
2.0 message (tools/list, tools/call) and one JSON reply. That is all this
backend needs, so it uses requests rather than adding the mcp SDK, and the web
server it brings, to the image.

The fraud_alerts_count result is used twice:
- routes/mcp.py shows it on the AI Mode tab;
- routes/ai.py passes it to the explanation as the customer's alert history.
"""

import itertools

import requests

from services.local_servers import BadServerResponse, ServerDisabled, flag_enabled, setting, unavailable

DEFAULT_URL = "http://localhost:8100/mcp"
START_COMMAND = "python -m mcp_server.server"
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 15
FRAUD_TOOL = "fraud_alerts_count"

# Streamable HTTP servers answer 406 unless both media types are accepted.
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
_request_ids = itertools.count(1)


class ToolFailed(RuntimeError):
    """The tool ran and reported an error (isError), e.g. it could not reach fraud-service."""


def enabled():
    return flag_enabled("MCP_ENABLED")


def server_url():
    return setting("MCP_SERVER_URL", DEFAULT_URL)


def _rpc(method, params, read_timeout=READ_TIMEOUT):
    """POST one JSON-RPC request and return its result object."""
    if not enabled():
        raise ServerDisabled("MCP is switched off in this environment (MCP_ENABLED=false)")

    url = server_url()
    message = {"jsonrpc": "2.0", "id": next(_request_ids), "method": method, "params": params}
    try:
        response = requests.post(url, json=message, headers=_HEADERS, timeout=(CONNECT_TIMEOUT, read_timeout))
    except requests.RequestException as exc:
        raise unavailable("MCP server", url, START_COMMAND, exc) from None

    if response.status_code >= 400:
        raise BadServerResponse(f"MCP server answered HTTP {response.status_code}: {response.text[:200]}")
    try:
        body = response.json()
    except ValueError:
        raise BadServerResponse("MCP server did not answer with JSON") from None
    if not isinstance(body, dict):
        raise BadServerResponse("MCP server's reply is not a JSON-RPC object")
    if body.get("error"):
        error = body["error"] if isinstance(body["error"], dict) else {}
        raise BadServerResponse(
            f"MCP error {error.get('code', '?')} for {method}: {error.get('message', 'no message')}"
        )
    result = body.get("result")
    if not isinstance(result, dict):
        raise BadServerResponse(f"MCP reply to {method} has no result")
    return result


def list_tools():
    """The tools registered on the shared server: name, description, arguments."""
    tools = []
    for tool in _rpc("tools/list", {}).get("tools") or []:
        if not isinstance(tool, dict):
            continue
        schema = tool.get("inputSchema") or {}
        tools.append({
            "name": tool.get("name", ""),
            "description": (tool.get("description") or "").strip().split("\n")[0],
            "arguments": sorted((schema.get("properties") or {}).keys()),
            "required": schema.get("required", []),
        })
    return tools


def call_tool(name, arguments, read_timeout=READ_TIMEOUT):
    """The tool's structured result, or ToolFailed carrying the tool's own message."""
    result = _rpc("tools/call", {"name": name, "arguments": arguments}, read_timeout)
    text = " ".join(
        block.get("text", "")
        for block in result.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if result.get("isError"):
        raise ToolFailed(text or f"{name} reported an error without a message")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise BadServerResponse(f"{name} returned no structured result")
    return structured


def fraud_alerts_count(customer_id=None, status=None, read_timeout=READ_TIMEOUT):
    """(arguments sent, result) for this feature's own tool. Callers validate
    the inputs first; the tool validates them again on the server."""
    arguments = {}
    if customer_id is not None:
        arguments["customer_id"] = customer_id
    if status is not None:
        arguments["status"] = status
    return arguments, call_tool(FRAUD_TOOL, arguments, read_timeout)
