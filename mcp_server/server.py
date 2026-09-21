"""The shared SmartBank MCP server.  Run from the repo root:

    python -m mcp_server.server

Lecture 7's Flask MCP pattern: FastMCP from the official `mcp` SDK, one
registered tool per feature, each tool reusing that feature's existing HTTP
API rather than duplicating its logic. Served over streamable HTTP on
localhost so the containerised backends can call it at
http://host.docker.internal:8100/mcp.

This process is NOT containerised and must not be added to docker-compose.yml
(Release 1 brief, Docker Compose Integration).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server import config
from mcp_server.tools import register_all, tool_names
from mcp_server.tools._contract import enforce_strict_arguments

INSTRUCTIONS = (
    "SmartBank shared MCP server. Every tool is read-only and returns a "
    "structured result from one feature's system of record. Tools reject "
    "arguments they do not declare and return isError when a feature service "
    "is unavailable; they never invent data."
)


def create_server() -> FastMCP:
    mcp = FastMCP(
        "SmartBank MCP",
        instructions=INSTRUCTIONS,
        host=config.MCP_HOST,
        port=config.MCP_PORT,
        streamable_http_path=config.MCP_PATH,
        # One request, one JSON reply. No session state to juggle from Flask.
        stateless_http=True,
        json_response=True,
        log_level=config.MCP_LOG_LEVEL,
    )
    register_all(mcp)
    enforce_strict_arguments(mcp)
    return mcp


mcp = create_server()


def _banner() -> None:
    rule = "=" * 72
    print(rule)
    print("  SmartBank - shared MCP server (not containerised)")
    print(f"  listening:  http://{config.MCP_HOST}:{config.MCP_PORT}{config.MCP_PATH}")
    print(f"  local url:  {config.local_url()}")
    print(f"  containers: http://host.docker.internal:{config.MCP_PORT}{config.MCP_PATH}")
    print("  tools:      " + ", ".join(tool_names()))
    print("  feature APIs:")
    for feature, url in config.SERVICE_URLS.items():
        print(f"    {feature:<13} {url}")
    print("  validate:   python -m mcp_server.validate")
    print(rule, flush=True)


if __name__ == "__main__":
    _banner()
    mcp.run(transport="streamable-http")
