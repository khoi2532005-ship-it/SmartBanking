"""Settings for the shared MCP server, read from the environment.

The server runs on the host, so service URLs default to localhost ports. The
names match `.env.example` exactly, so one `.env` configures the MCP server,
the RAG server and the agentic loop.

Containerised backends reach this server at http://host.docker.internal:8100/mcp,
which is why the bind address defaults to 0.0.0.0 rather than 127.0.0.1.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# ---- where this server listens -------------------------------------------
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8100"))
MCP_PATH = "/mcp"
MCP_LOG_LEVEL = os.getenv("MCP_LOG_LEVEL", "WARNING").upper()

# ---- the feature APIs the tools call (never a database file) -------------
SERVICE_URLS: dict[str, str] = {
    "accounts": os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001"),
    "loans": os.getenv("LOANS_SERVICE_URL", "http://localhost:5002"),
    "fraud": os.getenv("FRAUD_SERVICE_URL", "http://localhost:5003"),
    "budgeting": os.getenv("BUDGET_SERVICE_URL", "http://localhost:5004"),
    "transactions": os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005"),
}

# Fail fast into a readable tool error rather than hang a demo.
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 5


def local_url() -> str:
    """The URL a client on this machine uses."""
    host = "localhost" if MCP_HOST in ("0.0.0.0", "") else MCP_HOST
    return f"http://{host}:{MCP_PORT}{MCP_PATH}"
