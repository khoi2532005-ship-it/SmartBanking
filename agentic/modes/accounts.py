"""Accounts & Customers mode - William.

Drives the running accounts service the way a marker would at the showcase:
pull one customer's profile and accounts, compute the same rule-based risk
assessment the backend computes, then make the model explain *that specific*
result. OBSERVE checks the explanation states the risk_level and addresses
every one of the four checks - not just plausible-sounding filler - and
ADAPT retries with the specific complaint.

This is the loop-level twin of `services/accounts/backend/services/
account_logic.py`'s evaluate_risk(): the four checks and the two balance
thresholds below are kept identical on purpose so a run here proves the same
thing the live /api/ai/customers/<id>/risk-profile endpoint would. The loop
talks to the running service over HTTP only (see agentic/net.py) rather than
importing the backend package directly, so the assessment is recomputed here
from the raw customer/account JSON instead of calling that endpoint directly -
calling it would make the LLM call part of ACT's deterministic half, which is
exactly what OBSERVE is supposed to check independently.

If you change the risk rules in account_logic.py, change them here too.
"""

from __future__ import annotations

import os

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

ACCOUNTS_SERVICE_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001")
PROMPT_FAMILY = "accounts"

# Which customer the loop inspects. Overridable so the same run can be
# repeated against a different seeded customer for pre/post evidence.
CUSTOMER_ID = int(os.getenv("ACCOUNTS_LOOP_CUSTOMER", "1"))

# Kept identical to services/accounts/backend/services/account_logic.py.
LOW_BALANCE_THRESHOLD = 100.0
HEALTHY_BALANCE_THRESHOLD = 2000.0

CHECK_KEYWORDS = {
    "has_active_account": ["active account"],
    "no_negative_balances": ["negative", "overdrawn", "overdraw", "overdrew"],
    "healthy_total_balance": ["balance"],
    "contact_details_complete": ["contact", "email", "phone"],
}


def _evaluate_risk(customer: dict, accounts: list[dict]) -> dict:
    """Same rules as account_logic.evaluate_risk(), recomputed from the API's
    own JSON so this mode never has to import the backend package directly."""
    active = [a for a in accounts if str(a.get("status", "")).upper() == "ACTIVE"]
    total_balance = round(sum(float(a.get("balance") or 0) for a in active), 2)
    negative = [a for a in active if float(a.get("balance") or 0) < 0]
    has_negative_balance = bool(negative)

    checks = [
        {"check": "has_active_account", "passed": len(active) > 0},
        {"check": "no_negative_balances", "passed": not has_negative_balance},
        {"check": "healthy_total_balance", "passed": total_balance >= LOW_BALANCE_THRESHOLD},
        {
            "check": "contact_details_complete",
            "passed": bool(customer.get("email")) and bool(customer.get("phone")),
        },
    ]
    failed = [c for c in checks if not c["passed"]]

    if not active or has_negative_balance:
        risk_level = "HIGH"
    elif len(failed) >= 2 or total_balance < LOW_BALANCE_THRESHOLD:
        risk_level = "MEDIUM"
    elif total_balance >= HEALTHY_BALANCE_THRESHOLD and not failed:
        risk_level = "LOW"
    else:
        risk_level = "MEDIUM"

    return {
        "risk_level": risk_level,
        "checks": checks,
        "active_count": len(active),
        "total_balance": total_balance,
        "has_negative_balance": has_negative_balance,
    }


class AccountsMode(Mode):
    key = "accounts"
    label = "Accounts & Customers"
    owner = "William"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the AI risk-profile explanation is grounded in the "
                "customer's real account data and rule-based checks"
            ),
            checks=[
                "accounts service responds on /api/customers/<id>",
                f"customer {CUSTOMER_ID} has at least one account to assess",
                "the deterministic risk assessment computes a risk_level",
                "the AI explanation states the risk_level and addresses every check",
            ],
            stop_condition="An explanation passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        try:
            customer = net.get_json(f"{ACCOUNTS_SERVICE_URL}/api/customers/{CUSTOMER_ID}")
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"accounts service at {ACCOUNTS_SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d accounts",
            )

        accounts = customer.pop("accounts", None) or []
        if not accounts:
            return Evidence(
                ok=False,
                summary=(
                    f"Customer {CUSTOMER_ID} has no accounts to assess. Seed the "
                    "database (services/accounts/database/init_db.py) or set "
                    "ACCOUNTS_LOOP_CUSTOMER to a seeded customer."
                ),
            )

        assessment = _evaluate_risk(customer, accounts)

        return Evidence(
            ok=True,
            summary=(
                f"customer {customer.get('customer_id')} "
                f"({customer.get('first_name')} {customer.get('last_name')}): "
                f"{len(accounts)} account(s), {assessment['active_count']} active, "
                f"total balance ${assessment['total_balance']:,.2f}; "
                f"risk_level={assessment['risk_level']}"
            ),
            facts={"customer": customer, "accounts": accounts, "assessment": assessment},
            degraded=False,
            note="",
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, context_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY,
            "implementation/system_prompt.txt",
            "implementation/context_prompt.txt",
            "implementation/task_prompt.txt",
        )

        facts = evidence.facts
        customer = facts["customer"]
        assessment = facts["assessment"]

        check_lines = [
            f"- {c['check']}: {'PASSED' if c['passed'] else 'FAILED'}"
            for c in assessment["checks"]
        ]

        evidence_block = "\n".join([
            f"Customer: {customer.get('first_name')} {customer.get('last_name')} "
            f"(ID {customer.get('customer_id')})",
            f"Risk level (already decided by the rules - do not change it): "
            f"{assessment['risk_level']}",
            f"Active accounts: {assessment['active_count']}",
            f"Total balance across active accounts: ${assessment['total_balance']:,.2f}",
            f"Any active account overdrawn: {'yes' if assessment['has_negative_balance'] else 'no'}",
            "Checks:",
            *check_lines,
        ])

        # The Adapt stage, concretely: the previous verdict's complaint is
        # appended as a correction the model has to satisfy this time.
        correction = ""
        if feedback:
            correction = (
                "\n\nYour previous answer was rejected: "
                f"{feedback}. Fix exactly that. State the risk_level explicitly "
                "and address every check by name."
            )

        user_prompt = (
            f"{context_prompt}\n\n{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"
        )
        return system_prompt, user_prompt

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        assessment = evidence.facts["assessment"]
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()

        risk_level = assessment["risk_level"].lower()
        if risk_level not in text:
            reasons.append(
                f"it did not state the risk_level explicitly ('{assessment['risk_level']}')"
            )

        missing_checks = []
        for check in assessment["checks"]:
            name = check["check"]
            keywords = CHECK_KEYWORDS.get(name, [name.replace("_", " ")])
            if not any(kw in text for kw in keywords):
                missing_checks.append(name)
        if missing_checks:
            reasons.append("it did not address these checks: " + ", ".join(missing_checks))

        # A sentence that stops mid-word is a truncation, not an explanation.
        if len(output) > 40 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
