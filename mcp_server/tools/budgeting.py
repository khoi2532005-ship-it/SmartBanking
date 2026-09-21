"""budgeting_summary - Budgeting & Spending Insights (Bao).

Capability brief
    Question   How is one customer tracking against their budgets this month?
    Source     budgeting-service, GET /api/budgets/summary (owns the budgets)
    Operation  Read the budget-versus-actual summary for one customer/period
    Scope      Read-only. One customer, one month. Returns the summary the
               API already publishes: totals, per-category lines, statuses,
               unbudgeted categories, spending source. No raw transactions.
    Result     Structured summary, or isError with the reason
    Non-goals  Does not create, edit or delete budgets; does not generate
               AI insight; does not read other customers.
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

TOOL_NAME = "budgeting_summary"
FEATURE = "budgeting"
ENDPOINT = "/api/budgets/summary"


def budgeting_summary(customer_id: int, month: int, year: int) -> dict[str, Any]:
    """Budget-versus-actual summary for one customer and month.

    Returns each budget category with its limit, actual spend, percent used
    and status (ON_TRACK, NEAR_LIMIT or OVER_BUDGET), plus totals and any
    spending in categories with no budget set. Read-only.
    """
    require_customer_id(customer_id)
    require_month(month)
    require_year(year)

    base = config.SERVICE_URLS[FEATURE]
    with upstream(FEATURE):
        summary = get_json(
            base, ENDPOINT, {"customer_id": customer_id, "month": month, "year": year}
        )

    lines = summary.get("budgets") or []
    return {
        "source": source(FEATURE, base, ENDPOINT),
        "customer_id": customer_id,
        "month": month,
        "year": year,
        "budget_count": len(lines),
        "totals": summary.get("totals") or {},
        "budgets": [
            {
                "category": line.get("category"),
                "monthly_limit": line.get("monthly_limit"),
                "spent": line.get("spent"),
                "remaining": line.get("remaining"),
                "percent_used": line.get("percent_used"),
                "status": line.get("status"),
                "over_by": line.get("over_by", 0.0),
            }
            for line in lines
        ],
        "over_budget_categories": summary.get("over_budget_categories") or [],
        "unbudgeted_spending": summary.get("unbudgeted_spending") or [],
        "spending_source": summary.get("spending_source", "unknown"),
    }


def register(mcp: FastMCP) -> None:
    mcp.tool(name=TOOL_NAME, structured_output=True)(budgeting_summary)
