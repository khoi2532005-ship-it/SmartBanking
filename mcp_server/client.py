"""Synchronous MCP client helpers for host-side callers.

Used by `mcp_server/validate.py` and by the agentic loop's MCP validation
mode. Both run on the host from the repo root, so they can share this file.
The budgeting backend has its own copy in
`services/budgeting/backend/services/mcp_client.py` because its Docker image
does not include this package.

Speaks real MCP over streamable HTTP: `tools/list` and `tools/call` as
JSON-RPC, via the official SDK's client. Wrapped in `asyncio.run` so Flask
routes and plain scripts can call it without becoming async themselves.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

# The SDK's HTTP layer logs every request at INFO, which drowns a demo terminal.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

DEFAULT_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8100/mcp")
DEFAULT_TIMEOUT = float(os.getenv("MCP_CLIENT_TIMEOUT", "15"))


class MCPUnreachable(Exception):
    """The MCP server did not answer. Message is written for a person."""


class MCPProtocolError(Exception):
    """The server answered with a JSON-RPC error (unknown tool, bad request)."""


@dataclass
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


@dataclass
class ToolResult:
    tool: str
    arguments: dict[str, Any]
    is_error: bool
    structured: dict[str, Any] | None = None
    text: str = ""
    raw_content: list[dict[str, Any]] = field(default_factory=list)


def _unreachable(url: str, exc: BaseException) -> MCPUnreachable:
    name = type(exc).__name__
    if "Connect" in name or "refused" in str(exc).lower():
        return MCPUnreachable(
            f"MCP server at {url} refused the connection - start it with: "
            "python -m mcp_server.server"
        )
    if "Timeout" in name or "timed out" in str(exc).lower():
        return MCPUnreachable(f"MCP server at {url} did not answer in time")
    return MCPUnreachable(f"MCP server at {url} failed: {name}: {exc}")


def _run(coro_factory, url: str):
    async def runner():
        async with streamablehttp_client(url, timeout=DEFAULT_TIMEOUT) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await coro_factory(session)

    try:
        return asyncio.run(runner())
    except McpError as exc:
        raise MCPProtocolError(str(exc.error.message if hasattr(exc, "error") else exc)) from None
    except MCPProtocolError:
        raise
    except BaseException as exc:  # ExceptionGroup from anyio, httpx errors, OSError
        # anyio wraps connection failures in an ExceptionGroup; find the root cause.
        root = exc
        while getattr(root, "exceptions", None):
            root = root.exceptions[0]
        if isinstance(root, McpError):
            raise MCPProtocolError(str(root.error.message)) from None
        raise _unreachable(url, root) from None


def list_tools(url: str = DEFAULT_URL) -> list[ToolInfo]:
    """`tools/list` - the registered tool contracts."""
    async def go(session: ClientSession):
        result = await session.list_tools()
        return [
            ToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
                output_schema=getattr(t, "outputSchema", None),
            )
            for t in result.tools
        ]
    return _run(go, url)


def call_tool(name: str, arguments: dict[str, Any], url: str = DEFAULT_URL) -> ToolResult:
    """`tools/call` - returns the structured result or the tool's error content.

    A tool-level failure (validation, backend down, domain rule) comes back as
    `is_error=True` with readable `text`, not as an exception. FastMCP 1.x also
    answers an unknown tool name that way ("Unknown tool: <name>"); a malformed
    protocol request raises MCPProtocolError.
    """
    async def go(session: ClientSession):
        result = await session.call_tool(name, arguments)
        text = "\n".join(
            getattr(block, "text", "") for block in result.content if getattr(block, "text", "")
        )
        return ToolResult(
            tool=name,
            arguments=arguments,
            is_error=bool(result.isError),
            structured=result.structuredContent if not result.isError else None,
            text=text,
            raw_content=[block.model_dump() for block in result.content],
        )
    return _run(go, url)


def ping(url: str = DEFAULT_URL) -> bool:
    """True if the server answers `initialize`; raises MCPUnreachable otherwise."""
    async def go(session: ClientSession):
        return True
    return _run(go, url)
