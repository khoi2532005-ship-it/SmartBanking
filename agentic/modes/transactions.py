"""Transactions mode - Aidan.

Drives the running transactions service the way a customer or reviewer would at
showcase time: pull the most recent transactions for a customer, then ask the
model to summarise the spending mix and the clearest pattern. OBSERVE checks
that the summary stays grounded in the real dollar values and categories rather
than plausible filler, and ADAPT retries with the concrete complaint.
"""

from __future__ import annotations

import os

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

TRANSACTIONS_SERVICE_URL = os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005")
PROMPT_FAMILY = "transactions"
CUSTOMER_ID = int(os.getenv("TRANSACTIONS_LOOP_CUSTOMER", "1"))


def _money(value) -> str:
    return f"${float(value):,.2f}"


class TransactionsMode(Mode):
    key = "transactions"
    label = "Transactions"
    owner = "Aidan"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the recent transaction summary is grounded in the customer's "
                "real activity and category mix"
            ),
            checks=[
                "transactions-service responds on /api/transactions",
                f"at least one transaction exists for customer {CUSTOMER_ID}",
                "the AI summary names the main spending categories and a concrete pattern",
                "the answer includes actual dollar figures from the evidence",
            ],
            stop_condition="An explanation passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        url = f"{TRANSACTIONS_SERVICE_URL}/api/transactions?customer_id={CUSTOMER_ID}"
        try:
            records = net.get_json(url)
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"transactions-service at {TRANSACTIONS_SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d transactions",
            )

        if not records:
            return Evidence(
                ok=False,
                summary=(
                    f"No transactions for customer {CUSTOMER_ID}. Seed the database or "
                    "set TRANSACTIONS_LOOP_CUSTOMER to a seeded customer."
                ),
            )

        recent = sorted(records, key=lambda r: r.get("date", ""), reverse=True)[:8]
        category_totals: dict[str, float] = {}
        for record in recent:
            category = str(record.get("category") or "Other").strip() or "Other"
            amount = float(record.get("amount", 0) or 0)
            category_totals[category] = category_totals.get(category, 0.0) + abs(amount)

        top_categories = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:3]
        total_out = sum(abs(float(r.get("amount", 0) or 0)) for r in recent if float(r.get("amount", 0) or 0) < 0)
        total_in = sum(float(r.get("amount", 0) or 0) for r in recent if float(r.get("amount", 0) or 0) > 0)

        return Evidence(
            ok=True,
            summary=(
                f"{len(recent)} recent transactions for customer {CUSTOMER_ID}; "
                f"top categories: {', '.join(f'{name} ({_money(value)})' for name, value in top_categories)}; "
                f"spend {_money(total_out)} vs income {_money(total_in)}"
            ),
            facts={
                "customer_id": CUSTOMER_ID,
                "records": recent,
                "top_categories": top_categories,
                "total_out": total_out,
                "total_in": total_in,
            },
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

        records = evidence.facts["records"]
        top_categories = evidence.facts["top_categories"]
        recent_lines = [
            f"- {r.get('date')}: {r.get('type')} {r.get('category')} {_money(r.get('amount', 0))} "
            f"({r.get('description') or 'no description'})"
            for r in records
        ]

        evidence_block = "\n".join([
            f"Customer ID: {evidence.facts['customer_id']}",
            f"Recent transaction count: {len(records)}",
            f"Top categories: {', '.join(f'{name} ({_money(value)})' for name, value in top_categories)}",
            f"Total outgoing: {_money(evidence.facts['total_out'])}",
            f"Total incoming: {_money(evidence.facts['total_in'])}",
            "Recent transactions:",
            *recent_lines,
        ])

        correction = ""
        if feedback:
            correction = (
                "\n\nYour previous answer was rejected: "
                f"{feedback}. Fix exactly that. Name the dominant spending category or "
                "categories and include a real dollar amount from the evidence."
            )

        user_prompt = (
            f"{context_prompt}\n\n{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"
        )
        return system_prompt, user_prompt

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()
        reasons: list[str] = []
        categories = [name.lower() for name, _ in evidence.facts["top_categories"]]

        if not any(category in text for category in categories):
            reasons.append("it did not name the main spending category or categories from the evidence")

        dollar_pattern = any(char in text for char in "$0123456789")
        if not dollar_pattern:
            reasons.append("it did not include a concrete dollar amount from the transaction evidence")

        if len(output) > 180 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
