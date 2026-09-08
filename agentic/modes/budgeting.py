"""Budgeting & Spending Insights mode - Bao.

Drives the running budgets service the way a customer would at the showcase:
pull this month's budget-versus-actual summary, then make the model write the
spending insight. OBSERVE checks that the insight is grounded in the real
figures - it must quote the total spent and name every category that is over
budget - rather than plausible-sounding filler, and ADAPT retries with the
specific complaint.

This is the loop-level twin of `services/budgeting/backend/services/
insight_service.py`, which runs the same steps for one request inside the
API. The loop uses its own prompt family under `prompts/budgeting/
implementation/` so the review stage can be tuned without touching the
customer-facing prompts.

Actual spending comes from the Transactions feature over HTTP. When that
service is down the budgets API falls back to mock transactions and says so
in `spending_source`; this mode surfaces that as `degraded=True` so a pass
earned on mock data is never reported as a clean pass.
"""

from __future__ import annotations

import os
from datetime import date

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

BUDGET_SERVICE_URL = os.getenv("BUDGET_SERVICE_URL", "http://localhost:5004")
PROMPT_FAMILY = "budgeting"

# Which customer/period the loop inspects. Overridable so the same run can be
# repeated against a different month for pre/post evidence.
CUSTOMER_ID = int(os.getenv("BUDGET_LOOP_CUSTOMER", "1"))
MONTH = int(os.getenv("BUDGET_LOOP_MONTH", str(date.today().month)))
YEAR = int(os.getenv("BUDGET_LOOP_YEAR", str(date.today().year)))

STATUS_WORDS = {
    "OVER_BUDGET": "over budget",
    "NEAR_LIMIT": "near its limit",
    "ON_TRACK": "on track",
}


def _money(value) -> str:
    return f"${float(value):,.2f}"


class BudgetingMode(Mode):
    key = "budgeting"
    label = "Budgeting & Insights"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the spending insight is grounded in the customer's real "
                "budget-versus-actual figures for the period"
            ),
            checks=[
                "budgeting-service responds on /api/budgets/summary",
                f"at least one budget exists for customer {CUSTOMER_ID} in {MONTH:02d}/{YEAR}",
                "actual spending was retrieved (live Transactions API, or mock marked degraded)",
                "the AI insight states the total spent as a dollar figure",
                "the AI insight names every over-budget category, or says none are over",
            ],
            stop_condition="An insight passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        url = (
            f"{BUDGET_SERVICE_URL}/api/budgets/summary"
            f"?customer_id={CUSTOMER_ID}&month={MONTH}&year={YEAR}"
        )
        try:
            summary = net.get_json(url)
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"budgeting-service at {BUDGET_SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d budgeting-service",
            )

        lines = summary.get("budgets") or []
        if not lines:
            return Evidence(
                ok=False,
                summary=(
                    f"No budgets for customer {CUSTOMER_ID} in {MONTH:02d}/{YEAR}. "
                    "Seed the database (services/budgeting/database/init_db.py) or "
                    "set BUDGET_LOOP_MONTH / BUDGET_LOOP_YEAR to a seeded period."
                ),
            )

        totals = summary.get("totals") or {}
        over = [line for line in lines if line.get("over_budget")]
        near = [line for line in lines if line.get("status") == "NEAR_LIMIT"]
        source = summary.get("spending_source", "unknown")

        # Mock spending means the Transactions service was unreachable and the
        # budgets API fell back. The run still proves the loop, but the pass is
        # not earned on live cross-feature data, so mark it degraded.
        degraded = source != "transactions-api"

        # The category the insight most needs to get right: the worst overspend,
        # or the busiest category when nothing is over.
        focus = (
            max(over, key=lambda line: line.get("over_by", 0))
            if over
            else max(lines, key=lambda line: line.get("percent_used", 0))
        )

        return Evidence(
            ok=True,
            summary=(
                f"{len(lines)} budgets for customer {CUSTOMER_ID} in {MONTH:02d}/{YEAR}; "
                f"spent {_money(totals.get('total_spent', 0))} of "
                f"{_money(totals.get('total_limit', 0))}; "
                f"{len(over)} over budget"
                + (f" ({', '.join(l['category'] for l in over)})" if over else "")
                + (f"; {len(near)} near limit ({', '.join(l['category'] for l in near)})" if near else "")
                + f"; spending source: {source}"
            ),
            facts={
                "customer_id": CUSTOMER_ID,
                "month": MONTH,
                "year": YEAR,
                "totals": totals,
                "budgets": lines,
                "over_budget": over,
                "near_limit": near,
                "focus": focus,
                "unbudgeted": summary.get("unbudgeted_spending") or [],
                "spending_source": source,
            },
            degraded=degraded,
            note=(
                "spending came from mock transactions (Transactions API unreachable) - "
                "the insight is grounded in fallback data"
                if degraded else ""
            ),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, context_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY,
            "implementation/system_prompt.txt",
            "implementation/context_prompt.txt",
            "implementation/task_prompt.txt",
        )

        facts = evidence.facts
        totals = facts["totals"]

        category_lines = [
            f"- {line['category']}: spent {_money(line['spent'])} of "
            f"{_money(line['monthly_limit'])} limit ({line['percent_used']}%) - "
            f"{STATUS_WORDS.get(line['status'], line['status'])}"
            + (f", over by {_money(line['over_by'])}" if line.get("over_budget") else "")
            for line in facts["budgets"]
        ]

        unbudgeted = ""
        if facts["unbudgeted"]:
            unbudgeted = "\nSpending with no budget set: " + ", ".join(
                f"{u['category']} {_money(u['spent'])}" for u in facts["unbudgeted"]
            )

        evidence_block = "\n".join([
            f"Customer: {facts['customer_id']}",
            f"Period: {facts['month']:02d}/{facts['year']}",
            f"Total spent: {_money(totals.get('total_spent', 0))} of "
            f"{_money(totals.get('total_limit', 0))} budgeted "
            f"({totals.get('percent_used', 0)}% used)",
            f"Categories over budget: "
            + (", ".join(l["category"] for l in facts["over_budget"]) or "none"),
            f"Spending data source: {facts['spending_source']}",
            "Per category:",
            *category_lines,
        ]) + unbudgeted

        # The Adapt stage, concretely: the previous verdict's complaint is
        # appended as a correction the model has to satisfy this time.
        correction = ""
        if feedback:
            correction = (
                "\n\nYour previous answer was rejected: "
                f"{feedback}. Fix exactly that. Write every dollar figure as a "
                "number (for example $412.00, not 'four hundred'), and name each "
                "over-budget category by its exact name."
            )

        user_prompt = (
            f"{context_prompt}\n\n{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"
        )
        return system_prompt, user_prompt

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        facts = evidence.facts
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()
        digits_only = text.replace(",", "")

        # Total spent must appear as a number. Match loosely on the whole-dollar
        # part - the model may write 2169.97, 2,169.97 or 2170.
        try:
            spent = float(facts["totals"].get("total_spent", 0))
            whole = str(int(spent))
            rounded = str(int(round(spent)))
            if whole not in digits_only and rounded not in digits_only:
                reasons.append(
                    f"it did not state the total spent ({_money(spent)}) as a number"
                )
        except (TypeError, ValueError):
            pass

        # Every over-budget category must be named. If none are over, the
        # answer has to say so rather than invent a problem.
        over_names = [l["category"] for l in facts["over_budget"]]
        if over_names:
            missing = [name for name in over_names if name.lower() not in text]
            if missing:
                reasons.append(
                    "it did not name these over-budget categories: " + ", ".join(missing)
                )
        else:
            said_none = any(
                phrase in text
                for phrase in (
                    "no categories over", "none of your categories", "nothing is over",
                    "not over budget", "no category is over", "none are over",
                    "within budget", "under budget", "no overspending",
                    "haven't exceeded", "have not exceeded", "no categories are over",
                )
            )
            if not said_none:
                reasons.append(
                    "it did not say clearly that no category is over budget"
                )

        # The worst offender's overspend amount should be quoted too.
        focus = facts["focus"]
        if focus.get("over_budget"):
            over_by = str(int(float(focus.get("over_by", 0))))
            if over_by not in digits_only:
                reasons.append(
                    f"it did not state how much {focus['category']} is over by "
                    f"({_money(focus['over_by'])})"
                )

        # A sentence that stops mid-word is a truncation, not an insight.
        if len(output) > 40 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
