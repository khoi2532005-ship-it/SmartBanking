"""transactions_spending - Transactions (Aidan). SCAFFOLD - owner to confirm.

Capability brief
    Question   What did one customer spend this month, by category?
    Source     transactions-service, GET /api/transactions (owns transactions)
    Operation  Total withdrawals per category for one customer and month
    Scope      Read-only. One customer, one month. Totals per category and a
               transaction count; individual transactions and descriptions
               stay behind the boundary.
    Non-goals  Does not create or edit transactions; does not categorise.

Aidan: the filter uses your `customer_id`, `date_from` and `date_to` query
params and the `type`, `category` and `amount` fields your API returns.
Deposits are excluded from spending. Adjust if your contract changes.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server import config
from mcp_server.http import get_json
from mcp_server.tools._contract import (
    require_customer_id,
    require_month,
    require_year,
    source,
    upstream,
)

TOOL_NAME = "transactions_spending"
FEATURE = "transactions"
ENDPOINT = "/api/transactions"


def _month_bounds(month: int, year: int) -> tuple[str, str]:
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)
    return f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"


def transactions_spending(customer_id: int, month: int, year: int) -> dict[str, Any]:
    """Total spending per category for one customer in one month.

    Sums withdrawals and transfers (deposits are excluded) from the
    Transactions API and returns totals by category plus a transaction count.
    Read-only.
    """
    require_customer_id(customer_id)
    require_month(month)
    require_year(year)

    date_from, date_to = _month_bounds(month, year)
    base = config.SERVICE_URLS[FEATURE]
    with upstream(FEATURE):
        rows = get_json(
            base, ENDPOINT,
            {"customer_id": customer_id, "date_from": date_from, "date_to": date_to},
        )

    if not isinstance(rows, list):
        rows = []

    totals: dict[str, float] = {}
    counted = 0
    for row in rows:
        if str(row.get("type", "")).lower() == "deposit":
            continue
        try:
            amount = abs(float(row.get("amount", 0) or 0))
        except (TypeError, ValueError):
            continue
        category = row.get("category") or "Uncategorised"
        totals[category] = round(totals.get(category, 0.0) + amount, 2)
        counted += 1

    return {
        "source": source(FEATURE, base, ENDPOINT),
        "customer_id": customer_id,
        "month": month,
        "year": year,
        "transaction_count": counted,
        "total_spent": round(sum(totals.values()), 2),
        "totals_by_category": dict(sorted(totals.items())),
    }


def register(mcp: FastMCP) -> None:
    mcp.tool(name=TOOL_NAME, structured_output=True)(transactions_spending)
