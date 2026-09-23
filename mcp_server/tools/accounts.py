"""accounts_count - Accounts & Customers (William). SCAFFOLD - owner to confirm.

Capability brief
    Question   How many accounts exist, and in what states?
    Source     accounts-service, GET /api/accounts (owns customers and accounts)
    Operation  Count accounts, optionally for one customer, grouped by status
               and type
    Scope      Read-only. Aggregates only: no account numbers, no balances,
               no customer names cross the boundary.
    Non-goals  Does not open, close or edit accounts.

William: the counting below uses the `status` and `account_type` fields your
API returns today. Adjust the field names or add a filter if your contract
changes; keep the tool read-only and aggregate-only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server import config
from mcp_server.http import get_json
from mcp_server.tools._contract import require_customer_id, source, upstream

TOOL_NAME = "accounts_count"
FEATURE = "accounts"
ENDPOINT = "/api/accounts"


def accounts_count(customer_id: int | None = None) -> dict[str, Any]:
    """Number of bank accounts, grouped by status and account type.

    Pass customer_id to count one customer's accounts, or omit it for all.
    Returns counts only - never account numbers or balances. Read-only.
    """
    if customer_id is not None:
        require_customer_id(customer_id)

    base = config.SERVICE_URLS[FEATURE]
    with upstream(FEATURE):
        accounts = get_json(base, ENDPOINT, {"customer_id": customer_id})

    if not isinstance(accounts, list):
        accounts = []

    return {
        "source": source(FEATURE, base, ENDPOINT),
        "customer_id": customer_id,
        "account_count": len(accounts),
        "by_status": dict(Counter(str(a.get("status", "UNKNOWN")).upper() for a in accounts)),
        "by_type": dict(Counter(str(a.get("account_type", "UNKNOWN")).upper() for a in accounts)),
    }


def register(mcp: FastMCP) -> None:
    mcp.tool(name=TOOL_NAME, structured_output=True)(accounts_count)
