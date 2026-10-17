"""Configuration for the shared Multi-Agent Server.

Everything comes from the environment, under the same names the rest of the
project uses, so the one `.env` at the repo root configures every host
process. Loaded here so `python -m multi_agent_server.server` works from a
plain terminal, exactly like the MCP and RAG servers.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

HOST = os.getenv("MULTI_AGENT_HOST", "0.0.0.0")
PORT = int(os.getenv("MULTI_AGENT_PORT", "8300"))

# The feature APIs the Worker collects evidence from. Same variable names as
# mcp_server/config.py so one .env covers both servers; the Worker never reads
# a database file.
SERVICE_URLS: dict[str, str] = {
    "accounts": os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001"),
    "loans": os.getenv("LOANS_SERVICE_URL", "http://localhost:5002"),
    "fraud": os.getenv("FRAUD_SERVICE_URL", "http://localhost:5003"),
    "budgeting": os.getenv("BUDGET_SERVICE_URL", "http://localhost:5004"),
    "transactions": os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005"),
}
FEATURES = tuple(SERVICE_URLS)

# Evidence calls to feature APIs: fail fast, like every other client here.
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 5

# Bounded execution (Lecture 10): every stage has a maximum time to respond,
# and the Reviewer may send the Worker back at most this many times before
# the workflow escalates to the human.
STAGE_TIMEOUT = float(os.getenv("MULTI_AGENT_STAGE_TIMEOUT", "60"))
MAX_REVISIONS = int(os.getenv("MULTI_AGENT_MAX_REVISIONS", "1"))

# Roles stay generic. An override per role lets a demo assign a different
# model to the Planner, Worker or Reviewer without touching the workflow;
# unset, every role uses the shared AI-Mode model from agentic/llm.py.
ROLES = ("planner", "worker", "reviewer")


def role_model(role: str) -> str | None:
    return os.getenv(f"MULTI_AGENT_{role.upper()}_MODEL") or None


# Where state lives. Per-workflow JSON and the two append-only audit files are
# runtime output under multi_agent_server/data (gitignored, like rag_server/data),
# so demo runs never dirty the tree. `python -m multi_agent_server.validate
# --evidence` snapshots the audit records of its own workflows into
# docs/evidence/multi_agent/, which is what the report quotes.
DATA_DIR = Path(os.getenv("MULTI_AGENT_DATA_DIR", str(REPO_ROOT / "multi_agent_server" / "data")))
AUDIT_DIR = Path(os.getenv("MULTI_AGENT_AUDIT_DIR", str(DATA_DIR / "audit")))
HISTORY_FILE = "workflow_history.jsonl"
COORDINATION_FILE = "coordination_audit.jsonl"

MAX_REQUEST_CHARS = 1000

# Optional shared secret. When set, every /workflow* route requires
# "Authorization: Bearer <token>"; the feature backends, the terminal runners
# and the validate script read the same variable. Unset means open, which is
# fine for a local demo and is announced in the server banner.
API_TOKEN = os.getenv("MULTI_AGENT_API_TOKEN", "").strip()


def local_url() -> str:
    host = "localhost" if HOST in ("0.0.0.0", "") else HOST
    return f"http://{host}:{PORT}"
