"""Deterministic business rules for the Accounts & Customers feature.

These functions produce a structured, explainable assessment from raw
customer/account data. The AI layer (routes/ai.py) turns that structured
assessment into a plain-English summary or risk explanation - the same
"deterministic checks -> AI explains them" pattern used by the Loans &
Credit feature's eligibility engine.
"""

ACCOUNT_TYPES = ("SAVINGS", "CHECKING", "CREDIT")
ACCOUNT_STATUSES = ("ACTIVE", "INACTIVE", "CLOSED")

LOW_BALANCE_THRESHOLD = 100.0
HEALTHY_BALANCE_THRESHOLD = 2000.0


def summarize_accounts(accounts):
    """Roll a customer's accounts up into aggregate figures used by both
    the plain-English summary and the risk profile."""
    active = [a for a in accounts if str(a.get("status", "")).upper() == "ACTIVE"]
    closed = [a for a in accounts if str(a.get("status", "")).upper() == "CLOSED"]
    inactive = [a for a in accounts if str(a.get("status", "")).upper() == "INACTIVE"]

    total_balance = sum(float(a.get("balance") or 0) for a in active)
    negative_accounts = [a for a in active if float(a.get("balance") or 0) < 0]

    return {
        "account_count": len(accounts),
        "active_count": len(active),
        "inactive_count": len(inactive),
        "closed_count": len(closed),
        "total_balance": round(total_balance, 2),
        "negative_balance_accounts": [a["account_id"] for a in negative_accounts],
        "has_negative_balance": bool(negative_accounts),
    }


def evaluate_risk(customer, accounts):
    """Rule-based risk profile. Returns a transparent list of checks plus
    an overall LOW / MEDIUM / HIGH risk_level so the AI explanation can
    reference exactly why a customer was scored the way they were."""
    totals = summarize_accounts(accounts)
    checks = []

    checks.append(
        {
            "check": "has_active_account",
            "passed": totals["active_count"] > 0,
            "detail": (
                f"{totals['active_count']} active account(s) on file"
                if totals["active_count"] > 0
                else "No active accounts - customer cannot transact"
            ),
        }
    )

    checks.append(
        {
            "check": "no_negative_balances",
            "passed": not totals["has_negative_balance"],
            "detail": (
                "No active account is overdrawn"
                if not totals["has_negative_balance"]
                else f"{len(totals['negative_balance_accounts'])} active account(s) have a negative balance"
            ),
        }
    )

    checks.append(
        {
            "check": "healthy_total_balance",
            "passed": totals["total_balance"] >= LOW_BALANCE_THRESHOLD,
            "detail": (
                f"Total balance across active accounts is ${totals['total_balance']:,.2f}"
            ),
        }
    )

    checks.append(
        {
            "check": "contact_details_complete",
            "passed": bool(customer.get("email")) and bool(customer.get("phone")),
            "detail": (
                "Email and phone on file"
                if customer.get("email") and customer.get("phone")
                else "Missing email or phone number on the customer profile"
            ),
        }
    )

    failed = [c for c in checks if not c["passed"]]

    if not totals["active_count"] or totals["has_negative_balance"]:
        risk_level = "HIGH"
    elif len(failed) >= 2 or totals["total_balance"] < LOW_BALANCE_THRESHOLD:
        risk_level = "MEDIUM"
    elif totals["total_balance"] >= HEALTHY_BALANCE_THRESHOLD and not failed:
        risk_level = "LOW"
    else:
        risk_level = "MEDIUM"

    return {
        "risk_level": risk_level,
        "checks": checks,
        **totals,
    }
