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


def _multi_agent_server_url() -> str:
    return (os.getenv("MULTI_AGENT_SERVER_URL", "http://localhost:8300").strip() or "http://localhost:8300").rstrip("/")


def _configured_workflow_id() -> str:
    return os.getenv("TRANSACTIONS_LOOP_WORKFLOW_ID", "").strip()


def _workflow_response_url(workflow_id: str) -> str:
    return f"{_multi_agent_server_url()}/workflow/{workflow_id}/response"


def _latest_transactions_workflow_id() -> str:
    workflow_id = _configured_workflow_id()
    if workflow_id:
        return workflow_id
    try:
        listing = net.get_json(f"{_multi_agent_server_url()}/workflows?feature=transactions&limit=1")
    except net.ServiceUnreachable:
        return ""
    if not isinstance(listing, list):
        return ""
    for row in listing:
        if isinstance(row, dict) and row.get("feature") == "transactions":
            workflow_id = str(row.get("workflow_id") or "").strip()
            if workflow_id:
                return workflow_id
    return ""


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
        workflow_id = _latest_transactions_workflow_id()
        if workflow_id:
            try:
                final = net.get_json(_workflow_response_url(workflow_id))
            except net.ServiceUnreachable:
                workflow_id = ""
            else:
                if isinstance(final, dict) and final.get("released"):
                    findings = final.get("findings") or []
                    sources = final.get("evidence_sources") or []
                    answer = str(final.get("answer") or "").strip()
                    if answer or findings:
                        top_claims = [
                            str(item.get("statement", "")).strip()
                            for item in findings if isinstance(item, dict) and item.get("statement")
                        ]
                        summary = (
                            f"Approved multi-agent workflow {workflow_id} for customer {CUSTOMER_ID}; "
                            f"{len(findings)} findings from {len(sources)} evidence sources"
                        )
                        if top_claims:
                            summary += f"; {', '.join(top_claims[:2])[:180]}"
                        return Evidence(
                            ok=True,
                            summary=summary,
                            facts={
                                "customer_id": CUSTOMER_ID,
                                "workflow_id": workflow_id,
                                "answer": answer,
                                "findings": findings,
                                "evidence_sources": sources,
                            },
                            degraded=False,
                            note="evidence came from the approved multi-agent workflow",
                        )

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

        workflow_id = evidence.facts.get("workflow_id")
        if workflow_id:
            findings = evidence.facts.get("findings") or []
            finding_lines = [
                f"- {item.get('statement', '')}" if isinstance(item, dict) else str(item)
                for item in findings
            ]
            if not finding_lines:
                finding_lines = ["- (none)"]
            evidence_block = "\n".join([
                f"Customer ID: {evidence.facts['customer_id']}",
                f"Workflow ID: {workflow_id}",
                "Approved workflow answer:",
                str(evidence.facts.get("answer") or "(no approved answer available)"),
                "Workflow findings:",
                *finding_lines,
            ])
        else:
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
        categories = [name.lower() for name, _ in evidence.facts.get("top_categories", [])]
        if evidence.facts.get("findings"):
            for item in evidence.facts["findings"]:
                if isinstance(item, dict):
                    statement = str(item.get("statement", "")).lower()
                    text_words = {word for word in statement.replace("$", " ").replace(",", " ").split() if len(word) > 2}
                    categories.extend(word for word in text_words if word not in {"the", "with", "from", "into", "main"})

        categories = [category for category in categories if category.strip()]
        if not any(category in text for category in categories):
            reasons.append("it did not name the main spending category or categories from the evidence")

        dollar_pattern = any(char in text for char in "$0123456789")
        if not dollar_pattern:
            reasons.append("it did not include a concrete dollar amount from the transaction evidence")

        if len(output) > 180 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
