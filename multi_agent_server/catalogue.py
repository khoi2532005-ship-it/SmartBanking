"""Catalogue of the read-only feature endpoints the Worker may call.

This is the Planner's grounding and the Worker's allow-list: a plan may only
name endpoints listed here, with the parameters listed here. The entries are
the same read-only HTTP APIs the Release 1 MCP tools call (never a database
file), so one source of truth describes what the agents can reach.

Teammates extend their own feature's entry: add a path, its parameters and
whether a customer scope is required. Nothing else in the server changes.
"""

from __future__ import annotations

from typing import Any

# Parameters whose values must come from the workflow context. A plan that
# asks for another customer or another period is rejected by the contract.
CONTEXT_PARAMS = ("customer_id", "month", "year")

CATALOGUE: dict[str, list[dict[str, Any]]] = {
    "accounts": [
        {
            "path": "/api/accounts",
            "description": "Bank accounts of one customer; the Worker records counts by status and type, never balances or account numbers.",
            "params": {
                "customer_id": "the customer, from the context",
                "status": "optional: ACTIVE, FROZEN or CLOSED",
                "account_type": "optional: account type name",
            },
            "required": ["customer_id"],
            "default": True,
        },
    ],
    "loans": [
        {
            "path": "/api/loans",
            "description": "Loans held by one customer with type, requested amount and status.",
            "params": {
                "customer_id": "the customer, from the context",
                "status": "optional: PENDING, APPROVED, REJECTED or similar",
                "loan_type": "optional: loan type name",
            },
            "required": ["customer_id"],
            "default": True,
        },
    ],
    "fraud": [
        {
            "path": "/api/alerts",
            "description": "Fraud alerts raised for one customer; the Worker records counts by severity and status.",
            "params": {
                "customer_id": "the customer, from the context",
                "status": "optional: new, reviewed, dismissed or confirmed",
            },
            "required": ["customer_id"],
            "default": True,
        },
        {
            "path": "/api/rules",
            "description": "The detection rules currently configured (no customer data).",
            "params": {},
            "required": [],
        },
    ],
    "transactions": [
        {
            "path": "/api/transactions",
            "description": "Transactions of one customer in one month; the Worker turns month and year into the date range and records totals by category, not individual rows.",
            "params": {
                "customer_id": "the customer, from the context",
                "month": "the month, from the context",
                "year": "the year, from the context",
                "category": "optional: one category name",
            },
            "required": ["customer_id", "month", "year"],
            "translate_period": True,
            "default": True,
        },
    ],
    "budgeting": [
        {
            "path": "/api/budgets/summary",
            "description": "Budget-versus-actual summary for one customer and month: totals, each category's limit, spend, percent used and status, unbudgeted spending.",
            "params": {
                "customer_id": "the customer, from the context",
                "month": "the month, from the context",
                "year": "the year, from the context",
            },
            "required": ["customer_id", "month", "year"],
            "default": True,
        },
        {
            "path": "/api/transactions/spending",
            "description": "Spending by category for one customer and month, as the budgeting service reads it from the Transactions API.",
            "params": {
                "customer_id": "the customer, from the context",
                "month": "the month, from the context",
                "year": "the year, from the context",
            },
            "required": ["customer_id", "month", "year"],
            "default": True,
        },
        {
            "path": "/api/budgets",
            "description": "The budgets set by one customer, optionally for one period or category.",
            "params": {
                "customer_id": "the customer, from the context",
                "month": "optional: the month, from the context",
                "year": "optional: the year, from the context",
                "category": "optional: one category name",
            },
            "required": ["customer_id"],
        },
        {
            "path": "/api/budgets/insights",
            "description": "AI insights previously saved for one customer.",
            "params": {
                "customer_id": "the customer, from the context",
                "limit": "optional: how many recent insights, default 20",
            },
            "required": ["customer_id"],
        },
        {
            "path": "/api/categories",
            "description": "The budget category names the service knows.",
            "params": {},
            "required": [],
        },
    ],
}


def endpoints(feature: str) -> list[dict[str, Any]]:
    return CATALOGUE.get(feature, [])


def endpoint(feature: str, path: str) -> dict[str, Any] | None:
    for entry in endpoints(feature):
        if entry["path"] == path:
            return entry
    return None


def default_endpoints(feature: str) -> list[dict[str, Any]]:
    return [entry for entry in endpoints(feature) if entry.get("default")]


def describe(feature: str) -> str:
    """The catalogue as the Planner reads it in its task prompt."""
    lines = []
    for entry in endpoints(feature):
        lines.append(f"- GET {entry['path']}: {entry['description']}")
        if entry["params"]:
            for name, meaning in entry["params"].items():
                flag = "required" if name in entry["required"] else "optional"
                lines.append(f"    {name} ({flag}): {meaning}")
        else:
            lines.append("    no parameters")
    return "\n".join(lines)
