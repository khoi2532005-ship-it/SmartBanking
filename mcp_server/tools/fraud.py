"""fraud_alerts_count - Fraud Alerts (Khoi). SCAFFOLD - owner to confirm.

Capability brief
    Question   How many fraud alerts are open, and how severe are they?
    Source     fraud-service, GET /api/alerts (owns alerts and rules)
    Operation  Count alerts, optionally for one customer and/or one status,
               grouped by severity and status
    Scope      Read-only. Aggregates only: no merchant names, amounts or
               transaction ids cross the boundary.
    Non-goals  Does not run detection, create alerts or change alert status.

Khoi: the grouping uses the `severity` and `status` fields your API returns.
Adjust if your contract changes; keep the tool read-only and aggregate-only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server import config
from mcp_server.http import get_json
from mcp_server.tools._contract import ToolError, require_customer_id, source, upstream

TOOL_NAME = "fraud_alerts_count"
FEATURE = "fraud"
ENDPOINT = "/api/alerts"
ALERT_STATUSES = ("new", "reviewed", "dismissed", "confirmed")


def fraud_alerts_count(customer_id: int | None = None, status: str | None = None) -> dict[str, Any]:
    """Number of fraud alerts, grouped by severity and status.

    Pass customer_id to count one customer's alerts and/or status (one of
    new, reviewed, dismissed, confirmed) to narrow further. Counts only. Read-only.
    """
    if customer_id is not None:
        require_customer_id(customer_id)
    if status is not None:
        # Rejected here, before the backend: an unknown status would otherwise
        # come back as a count of 0 that reads like a real answer.
        status = status.strip().lower()
        if status not in ALERT_STATUSES:
            raise ToolError(f"status must be one of {', '.join(ALERT_STATUSES)}, got {status!r}")

    base = config.SERVICE_URLS[FEATURE]
    with upstream(FEATURE):
        alerts = get_json(base, ENDPOINT, {"customer_id": customer_id, "status": status})

    if not isinstance(alerts, list):
        alerts = []

    return {
        "source": source(FEATURE, base, ENDPOINT),
        "customer_id": customer_id,
        "status_filter": status,
        "alert_count": len(alerts),
        "by_severity": dict(Counter(str(a.get("severity", "unknown")).lower() for a in alerts)),
        "by_status": dict(Counter(str(a.get("status", "unknown")).lower() for a in alerts)),
    }


def register(mcp: FastMCP) -> None:
    mcp.tool(name=TOOL_NAME, structured_output=True)(fraud_alerts_count)
