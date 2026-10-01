"""Typed client for the shared MCP server (Release 1)."""

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
    "Accept": "application/json, text/event-stream",
}
_ids = itertools.count(1)


class MCPDisabled(RuntimeError):
    """MCP_ENABLED is off in this environment."""


class MCPUnreachable(RuntimeError):
    """The MCP server did not answer."""


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


def server_url() -> str:
    return os.getenv("MCP_SERVER_URL", DEFAULT_URL).strip() or DEFAULT_URL


def enabled() -> bool:
    return os.getenv("MCP_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def _read_timeout() -> float:
    try:
        return float(os.getenv("MCP_CLIENT_TIMEOUT", "30"))
    except ValueError:
        return 30.0


def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if not enabled():
        raise MCPDisabled("MCP integration is disabled in this environment (MCP_ENABLED=false)")

    url = server_url()
    payload = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params}
    try:
        response = requests.post(
            url, json=payload, headers=_HEADERS, timeout=(CONNECT_TIMEOUT, _read_timeout())
        )
    except requests.ConnectionError:
        raise MCPUnreachable(f"shared MCP server at {url} refused the connection - {START_HINT}") from None
    except requests.Timeout:
        raise MCPUnreachable(f"shared MCP server at {url} did not answer within {_read_timeout():.0f}s") from None
    except requests.RequestException as exc:
        raise MCPUnreachable(f"request to shared MCP server at {url} failed: {type(exc).__name__}") from None

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


def list_tools() -> list[ToolInfo]:
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
    arguments = dict(arguments or {})
    result = _rpc("tools/call", {"name": name, "arguments": arguments})
    return _parse_tool_result(name, arguments, result)


def transactions_spending(customer_id: int, month: int, year: int) -> ToolResult:
    return call_tool(
        "transactions_spending",
        {"customer_id": int(customer_id), "month": int(month), "year": int(year)},
    )


def status() -> dict[str, Any]:
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
