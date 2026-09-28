"""Typed client for the shared MCP server (Release 1).

The MCP server runs on the host (python -m mcp_server.server) and this
backend runs in a container, so the two talk over HTTP at MCP_SERVER_URL
(http://host.docker.internal:8100/mcp in Compose, localhost in dev).

Why plain HTTP and not the `mcp` SDK: the server is stateless streamable
HTTP with JSON responses, so one MCP request is one POST carrying a JSON-RPC
2.0 message (`tools/list`, `tools/call`) and one JSON reply - exactly the
wire protocol the SDK client would send. Pulling the SDK into this image
would add a web server (starlette, uvicorn) and twenty other packages to
make a client call. The host-side helper in mcp_server/client.py does use
the SDK; both speak the same protocol to the same server.

Behaviour the routes rely on:
- MCP_ENABLED=false raises MCPDisabled before any network call. CI runs with
  the integration disabled; the code path stays in the image.
- A server that is down raises MCPUnreachable with a one-sentence message
  that says how to start it. 2s connect timeout so a demo never hangs.
- A tool-level failure (bad argument, feature API down) is NOT an exception:
  it comes back as ToolResult(is_error=True, text=<reason>), mirroring MCP's
  `isError` result semantics. A JSON-RPC error (unknown method, malformed
  request) raises MCPProtocolError.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_URL = "http://localhost:8100/mcp"
CONNECT_TIMEOUT = 2
START_HINT = "start it on the host with: python -m mcp_server.server"

_HEADERS = {
    "Content-Type": "application/json",
    # Streamable HTTP servers answer 406 without both media types listed.
    "Accept": "application/json, text/event-stream",
}
_ids = itertools.count(1)


class MCPDisabled(RuntimeError):
    """MCP_ENABLED is off in this environment (for example CI)."""


class MCPUnreachable(RuntimeError):
    """The MCP server did not answer. Message is written for a person."""


class MCPProtocolError(RuntimeError):
    """The server answered with a JSON-RPC error or something that is not MCP."""


@dataclass
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    structured: dict[str, Any] | None = None
    text: str = ""


# ---------------------------------------------------------------------------
# Settings - read at call time so tests and CI can flip them with the environment
# ---------------------------------------------------------------------------

def server_url() -> str:
    return os.getenv("MCP_SERVER_URL", DEFAULT_URL).strip() or DEFAULT_URL


def enabled() -> bool:
    return os.getenv("MCP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _read_timeout() -> float:
    try:
        return float(os.getenv("MCP_CLIENT_TIMEOUT", "30"))
    except ValueError:
        return 30.0


# ---------------------------------------------------------------------------
# JSON-RPC transport
# ---------------------------------------------------------------------------

def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """POST one JSON-RPC request and return its `result`, or raise."""
    if not enabled():
        raise MCPDisabled("MCP integration is disabled in this environment (MCP_ENABLED=false)")

    url = server_url()
    payload = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
    try:
        response = requests.post(
            url, json=payload, headers=_HEADERS, timeout=(CONNECT_TIMEOUT, _read_timeout())
        )
    except requests.ConnectionError:
        raise MCPUnreachable(f"MCP server at {url} refused the connection - {START_HINT}") from None
    except requests.Timeout:
        raise MCPUnreachable(f"MCP server at {url} did not answer within {_read_timeout():.0f}s") from None
    except requests.RequestException as exc:
        raise MCPUnreachable(f"request to MCP server at {url} failed: {type(exc).__name__}") from None

    if response.status_code >= 400:
        raise MCPProtocolError(
            f"HTTP {response.status_code} from MCP server at {url}: {response.text[:200]}"
        )
    try:
        body = response.json()
    except ValueError:
        raise MCPProtocolError(f"MCP server at {url} did not return JSON") from None

    if not isinstance(body, dict):
        raise MCPProtocolError("MCP server returned a non-object JSON-RPC reply")
    if "error" in body:
        err = body["error"] or {}
        raise MCPProtocolError(
            f"JSON-RPC error {err.get('code', '?')} for {method}: {err.get('message', 'unknown error')}"
        )
    result = body.get("result")
    if not isinstance(result, dict):
        raise MCPProtocolError(f"JSON-RPC reply for {method} carried no result object")
    return result


def _parse_tool_result(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> ToolResult:
    """Map an MCP CallToolResult into ToolResult, keeping isError semantics."""
    is_error = bool(result.get("isError"))
    text = "\n".join(
        str(block.get("text", "")) for block in result.get("content") or []
        if isinstance(block, dict) and block.get("type", "text") == "text" and block.get("text")
    )
    structured = result.get("structuredContent") if not is_error else None
    return ToolResult(
        tool=name,
        arguments=arguments,
        is_error=is_error,
        structured=structured if isinstance(structured, dict) else None,
        text=text,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_tools() -> list[ToolInfo]:
    """`tools/list` - the registered tool contracts."""
    result = _rpc("tools/list", {})
    return [
        ToolInfo(
            name=str(t.get("name", "")),
            description=str(t.get("description", "") or ""),
            input_schema=t.get("inputSchema") or {},
        )
        for t in result.get("tools") or []
        if isinstance(t, dict)
    ]


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
    """`tools/call` - structured result, or is_error=True with the tool's reason."""
    arguments = dict(arguments or {})
    result = _rpc("tools/call", {"name": name, "arguments": arguments})
    return _parse_tool_result(name, arguments, result)


def budgeting_summary(customer_id: int, month: int, year: int) -> ToolResult:
    """This feature's own tool, invoked through the shared server."""
    return call_tool(
        "budgeting_summary",
        {"customer_id": int(customer_id), "month": int(month), "year": int(year)},
    )


def status() -> dict[str, Any]:
    """Cheap health summary for /api/agents/status: probes with tools/list."""
    info: dict[str, Any] = {"enabled": enabled(), "url": server_url(), "reachable": None, "tools": []}
    if not info["enabled"]:
        info["note"] = "disabled (MCP_ENABLED=false)"
        return info
    try:
        info["tools"] = [t.name for t in list_tools()]
        info["reachable"] = True
    except (MCPUnreachable, MCPProtocolError) as exc:
        info["reachable"] = False
        info["error"] = str(exc)
    return info
