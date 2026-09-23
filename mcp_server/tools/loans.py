"""loans_list - Loans & Credit (David). SCAFFOLD - owner to confirm.

Capability brief
    Question   Which loans does one customer have, and in what state?
    Source     loans-service, GET /api/loans (owns loans)
    Operation  List one customer's loans, optionally filtered by status
    Scope      Read-only. Bounded to one customer (customer_id is required
               so the tool can never dump every loan in the bank). Returns
               id, type, requested amount and status per loan.
    Non-goals  Does not apply for, approve, decline or repay loans.

David: the fields picked out below (loan_id, loan_type, requested_amount,
status) come from your seed schema. Rename or add fields to match what you
want other features to see; keep it read-only and one-customer.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server import config
from mcp_server.http import get_json
from mcp_server.tools._contract import require_customer_id, source, upstream

TOOL_NAME = "loans_list"
FEATURE = "loans"
ENDPOINT = "/api/loans"


def loans_list(customer_id: int, status: str | None = None) -> dict[str, Any]:
    """Loans held by one customer, with type, requested amount and status.

    Optionally filter by status (for example PENDING or APPROVED). Read-only.
    """
    require_customer_id(customer_id)

    base = config.SERVICE_URLS[FEATURE]
    with upstream(FEATURE):
        loans = get_json(base, ENDPOINT, {"customer_id": customer_id, "status": status})

    if not isinstance(loans, list):
        loans = []

    return {
        "source": source(FEATURE, base, ENDPOINT),
        "customer_id": customer_id,
        "status_filter": status,
        "loan_count": len(loans),
        "loans": [
            {
                "loan_id": loan.get("loan_id"),
                "loan_type": loan.get("loan_type"),
                "requested_amount": loan.get("requested_amount"),
                "status": loan.get("status"),
            }
            for loan in loans
        ],
    }


def register(mcp: FastMCP) -> None:
    mcp.tool(name=TOOL_NAME, structured_output=True)(loans_list)
