"""Small synchronous MCP client carried by this feature backend.

The shared MCP server (mcp_server/) runs on the host over streamable HTTP at
http://localhost:8100/mcp; Compose containers reach it through MCP_SERVER_URL
(defaults to http://host.docker.internal:8100/mcp). This image copies only its
own service folder, so it cannot import mcp_server.client - like every feature
backend it carries a tiny client of its own that speaks the same JSON-RPC
messages (initialize, initialized, tools/call) with the requests library.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8100/mcp")
MCP_TIMEOUT = float(os.getenv("MCP_CLIENT_TIMEOUT", "15"))
PROTOCOL_VERSION = "2025-06-18"

log = logging.getLogger(__name__)


class MCPUnavailable(Exception):
    """The shared MCP server did not answer. Message is written for a person."""


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    """POST one JSON-RPC message and return the parsed JSON body."""
    try:
        response = requests.post(
            MCP_SERVER_URL,
            headers=_headers(),
            data=json.dumps(payload),
            timeout=MCP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MCPUnavailable(
            f"shared MCP server at {MCP_SERVER_URL} did not answer: {type(exc).__name__}. "
            "Start it with 'python -m mcp_server.server'."
        ) from None

    if response.status_code >= 400:
        raise MCPUnavailable(
            f"shared MCP server at {MCP_SERVER_URL} answered HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )

    # A notification (notifications/initialized) is acknowledged with 202 and
    # an empty body, not JSON.
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise MCPUnavailable(
            f"shared MCP server at {MCP_SERVER_URL} did not return JSON"
        ) from None


def _reply(what: str, body: dict[str, Any]) -> dict[str, Any]:
    if "error" in body:
        message = body["error"].get("message", "JSON-RPC error") if isinstance(body["error"], dict) else body["error"]
        raise MCPUnavailable(f"MCP {what} failed: {message}")
    return body.get("result", {})


def initialize() -> dict[str, Any]:
    """`initialize` - the server's capabilities. Raises MCPUnavailable when down."""
    return _reply(
        "initialize",
        _post({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "smartbank-loans", "version": "0.1"},
            },
        }),
    )


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """`initialize` + `notifications/initialized` + `tools/call`.

    Returns the tool result: is_error, structured content and text. A tool
    error (validation, feature service down) is a result, not an exception;
    only an unreachable server raises MCPUnavailable.
    """
    initialize()
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    result = _reply(
        "tools/call",
        _post({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }),
    )

    text = "\n".join(
        block.get("text", "")
        for block in result.get("content", [])
        if block.get("type") == "text" and block.get("text")
    )
    return {
        "tool": name,
        "arguments": arguments or {},
        "is_error": bool(result.get("isError")),
        "structured": result.get("structuredContent"),
        "text": text,
    }


def ping() -> dict[str, Any]:
    """True when the server answers initialize."""
    return initialize()