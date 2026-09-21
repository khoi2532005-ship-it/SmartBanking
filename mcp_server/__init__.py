"""SmartBank shared MCP server (Release 1).

One non-containerised Model Context Protocol server, run locally on the host
and used by every student feature. It exposes one bounded, read-only tool per
feature; each tool calls that feature's existing HTTP API and never opens a
database file.

Run it from the repo root:  python -m mcp_server.server
Validate it:                python -m mcp_server.validate
"""

__all__ = ["client", "config", "server", "tools"]
