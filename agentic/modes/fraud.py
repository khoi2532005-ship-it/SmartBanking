"""Fraud Alerts mode - Khoi.

The reference implementation. It drives the running fraud service the same way
a marker would at the showcase: pull the enabled rules and the alerts the
detection run produced, pick one real alert, and make the model explain it.
OBSERVE then checks the explanation is actually grounded in that alert rather
than plausible-sounding filler, and ADAPT retries with the specific complaint.

This is the loop-level twin of `services/fraud-alerts/backend/services/
explain.py`, which does the same four stages for a single alert inside the
request path. Same prompt files, so fixing a prompt fixes both.
"""

from __future__ import annotations

import os

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

FRAUD_SERVICE_URL = os.getenv("FRAUD_SERVICE_URL", "http://localhost:5003")
PROMPT_FAMILY = "fraud-alerts"


class FraudMode(Mode):
    key = "fraud"
    label = "Fraud Alerts"
    owner = "Khoi"

    def plan(self) -> Plan:
        return Plan(
            goal="Verify fraud alert explanations are grounded in the triggering rule and transaction",
            checks=[
                "fraud-service responds on /api/rules and /api/alerts",
                "at least one enabled rule exists",
                "at least one alert exists to explain",
                "the AI explanation names the triggered rule and the transaction amount",
            ],
            stop_condition="An explanation passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        try:
            rules = net.get_json(f"{FRAUD_SERVICE_URL}/api/rules?enabled=true")
            alerts = net.get_json(f"{FRAUD_SERVICE_URL}/api/alerts")
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"fraud-service at {FRAUD_SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d fraud-service",
            )

        if not rules:
            return Evidence(ok=False, summary="No enabled rules. Seed the database first.")
        if not alerts:
            return Evidence(
                ok=False,
                summary="No alerts to explain. Run detection first: "
                        f"curl -X POST {FRAUD_SERVICE_URL}/api/detection/run",
            )

        rules_by_id = {r["rule_id"]: r for r in rules}

        # Explain the first alert whose rule is still enabled - an alert left
        # over from a since-disabled rule would be unfair to grade the model on.
        alert = next((a for a in alerts if a.get("rule_id") in rules_by_id), None)
        if alert is None:
            return Evidence(
                ok=False,
                summary=f"{len(alerts)} alerts exist but none map to a currently "
                        "enabled rule. Re-run detection.",
            )

        rule = rules_by_id[alert["rule_id"]]
        degraded = bool(alert.get("degraded")) or alert.get("transaction_recipient") is None

        return Evidence(
            ok=True,
            summary=(
                f"{len(rules)} enabled rules, {len(alerts)} alerts; "
                f"explaining alert {alert.get('alert_id')} "
                f"(rule '{rule.get('rule_name')}', ${alert.get('transaction_amount')})"
            ),
            facts={"alert": alert, "rule": rule,
                   "rule_count": len(rules), "alert_count": len(alerts)},
            degraded=degraded,
            note="alert is missing recipient detail - explanation will be thinner" if degraded else "",
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, context_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY,
            "implementation/system_prompt.txt",
            "implementation/context_prompt.txt",
            "implementation/task_prompt.txt",
        )

        alert = evidence.facts["alert"]
        rule = evidence.facts["rule"]

        threshold = str(rule.get("threshold_value"))
        if rule.get("threshold_secondary") is not None:
            threshold += f" / {rule.get('threshold_secondary')}"

        evidence_block = "\n".join([
            f"Alert ID: {alert.get('alert_id')}",
            f"Rule triggered: {rule.get('rule_name')} ({rule.get('rule_type')})",
            f"Threshold: {threshold}",
            f"Transaction amount: ${alert.get('transaction_amount')}",
            f"Recipient: {alert.get('transaction_recipient')}",
            f"Date/time: {alert.get('transaction_datetime')}",
            f"Category: {alert.get('transaction_category')}",
            f"Severity: {alert.get('severity')}",
        ])

        # The Adapt stage, concretely: the previous verdict's complaint is
        # appended as a correction the model has to satisfy this time.
        correction = ""
        if feedback:
            correction = (
                "\n\nYour previous answer was rejected: "
                f"{feedback}. Fix exactly that. Name the rule and state the "
                "dollar amount explicitly."
            )

        user_prompt = (
            f"{context_prompt}\n\n{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"
        )
        return system_prompt, user_prompt

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        alert = evidence.facts["alert"]
        rule = evidence.facts["rule"]
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()

        rule_name = (rule.get("rule_name") or "").lower()
        rule_type = (rule.get("rule_type") or "").replace("_", " ").lower()
        if rule_name not in text and rule_type not in text:
            reasons.append(f"it did not name the triggered rule ('{rule.get('rule_name')}')")

        # Match the amount loosely - the model may write 1500, 1,500 or 1500.00.
        try:
            amount = float(alert.get("transaction_amount", 0))
            whole = str(int(amount))
            if whole not in text.replace(",", ""):
                reasons.append(f"it did not state the transaction amount (${amount:.2f})")
        except (TypeError, ValueError):
            pass

        # A sentence that stops mid-word is a truncation, not an explanation.
        if len(output) > 40 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
