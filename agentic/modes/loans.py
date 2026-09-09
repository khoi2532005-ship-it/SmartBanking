"""Loans & Credit mode - David.

Drives the running loans service the way a customer would at the showcase:
pull a loan application that has already been decided (APPROVED or REJECTED)
plus its eligibility assessment, then make the model explain the decision.
OBSERVE checks that the explanation is grounded in the real loan - it must
name the loan type, the requested amount, and the eligibility checks that
fired - rather than plausible-sounding filler, and ADAPT retries with the
specific complaint.

This is the loop-level twin of `services/loans/backend/routes/ai.py`
(`/api/ai/loans/<loan_id>/explain-decision`), which does the same steps for a
single loan inside the request path. The loop uses its own prompt family under
`prompts/loans/implementation/` so the review stage can be tuned without
touching the customer-facing prompts.
"""

from __future__ import annotations

import os

from agentic import net, prompts
from agentic.core import Evidence, Mode, Plan, Verdict

LOANS_SERVICE_URL = os.getenv("LOANS_SERVICE_URL", "http://localhost:5002")
PROMPT_FAMILY = "loans"  # -> prompts/loans/implementation/

_STATUS = ("APPROVED", "REJECTED")


def _money(value) -> str:
    return f"${float(value):,.2f}"


class LoansMode(Mode):
    key = "loans"
    label = "Loans & Credit"
    owner = "David"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the loan decision explanation is grounded in the real "
                "loan application and its eligibility assessment"
            ),
            checks=[
                "loan-service responds on /api/loans and /api/loans/<id>/eligibility",
                "at least one decided (APPROVED or REJECTED) loan exists to explain",
                "the eligibility assessment was retrieved with its checks",
                "the AI explanation states the loan type and the requested dollar amount",
                "the AI explanation names the eligibility checks that passed, and any that failed",
            ],
            stop_condition="An explanation passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        try:
            loans = net.get_json(f"{LOANS_SERVICE_URL}/api/loans")
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"loan-service at {LOANS_SERVICE_URL}: {exc}. "
                        "Start it with: docker compose up -d loan-service",
            )

        # Pick a decided loan to explain - either an approved or a rejected one,
        # preferring rejected so the explanation has a failure to talk about.
        decided = [loan for loan in loans if loan.get("status") in _STATUS]
        if not decided:
            return Evidence(
                ok=False,
                summary=(
                    f"{len(loans)} loans found but none decided. Create and decide "
                    "one first: POST /api/loans then POST /api/loans/<id>/decision "
                    "(APPROVE or REJECT)."
                ),
            )

        loan = next(
            (l for l in decided if l.get("status") == "REJECTED"),
            decided[0],
        )

        try:
            assessment_payload = net.get_json(
                f"{LOANS_SERVICE_URL}/api/loans/{loan['loan_id']}/eligibility"
            )
        except net.ServiceUnreachable as exc:
            return Evidence(
                ok=False,
                summary=f"loan-service eligibility for loan {loan['loan_id']}: {exc}. "
                        "Start it with: docker compose up -d loan-service",
            )

        assessment = assessment_payload.get("eligibility") or {}
        checks = assessment.get("checks") or []
        if not checks:
            return Evidence(
                ok=False,
                summary=f"Eligibility for loan {loan['loan_id']} returned no checks.",
            )

        failed = [c for c in checks if not c.get("passed")]

        return Evidence(
            ok=True,
            summary=(
                f"{len(loans)} loans; explaining {loan.get('status')} loan "
                f"{loan.get('loan_id')} ({loan.get('loan_type')}, "
                f"{_money(loan.get('requested_amount'))}) - "
                f"{len(checks)} eligibility checks, {len(failed)} failed"
            ),
            facts={
                "loan": loan,
                "assessment": assessment,
                "checks": checks,
                "failed_checks": failed,
            },
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, context_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY,
            "implementation/system_prompt.txt",
            "implementation/context_prompt.txt",
            "implementation/task_prompt.txt",
        )

        loan = evidence.facts["loan"]
        assessment = evidence.facts["assessment"]
        checks = evidence.facts["checks"]

        check_lines = [
            f"- {c.get('check')}: {'passed' if c.get('passed') else 'failed'} - "
            f"{c.get('detail', '')}"
            for c in checks
        ]

        evidence_block = "\n".join([
            f"Loan ID: {loan.get('loan_id')}",
            f"Status: {loan.get('status')}",
            f"Loan type: {loan.get('loan_type')}",
            f"Requested amount: {_money(loan.get('requested_amount'))}",
            f"Approved amount: "
            f"{_money(loan.get('approved_amount')) if loan.get('approved_amount') is not None else 'n/a'}",
            f"Application date: {loan.get('application_date')}",
            f"Purpose: {loan.get('loan_purpose')}",
            f"Proposed interest rate: "
            f"{loan.get('interest_rate')}%" if loan.get("interest_rate") is not None else "",
            f"Eligibility: {'eligible' if assessment.get('eligible') else 'not eligible'}",
            "Checks:",
            *check_lines,
        ])

        # The Adapt stage, concretely: the previous verdict's complaint is
        # appended as a correction the model has to satisfy this time.
        correction = ""
        if feedback:
            correction = (
                "\n\nYour previous answer was rejected: "
                f"{feedback}. Fix exactly that. Name the loan type, state the "
                "requested dollar amount, and reference the specific eligibility "
                "checks (passed and failed) explicitly."
            )

        user_prompt = (
            f"{context_prompt}\n\n{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"
        )
        return system_prompt, user_prompt

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        loan = evidence.facts["loan"]
        checks = evidence.facts["checks"]
        failed = evidence.facts["failed_checks"]
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the answer was empty"])

        text = output.lower()
        digits_only = text.replace(",", "")

        # The loan type must be named.
        loan_type = (loan.get("loan_type") or "").lower()
        if loan_type and loan_type not in text:
            reasons.append(f"it did not name the loan type ('{loan.get('loan_type')}')")

        # The requested amount must appear as a number.
        try:
            amount = float(loan.get("requested_amount", 0))
            whole = str(int(amount))
            rounded = str(int(round(amount)))
            if whole not in digits_only and rounded not in digits_only:
                reasons.append(
                    f"it did not state the requested amount ({_money(amount)}) as a number"
                )
        except (TypeError, ValueError):
            pass

        # The status must be stated as approved or rejected.
        if not any(word in text for word in ("approv", "reject", "declin")):
            reasons.append("it did not state whether the loan was approved or rejected")

        # Every failed check must be explained; every check name should appear.
        check_names = [c.get("check", "") for c in checks if c.get("check")]
        if check_names:
            mentioned = any(name.replace("_", " ") in text for name in check_names)
            if not mentioned:
                reasons.append(
                    "it did not reference any of the eligibility checks "
                    f"({', '.join(check_names)})"
                )

        # Every failed check must be explained by name, so the retry prompt can
        # point at exactly what is missing.
        for c in failed:
            label = (c.get("check") or "").replace("_", " ").lower()
            if label and label not in text:
                reasons.append(
                    f"it did not explain why the '{c.get('check')}' check failed: "
                    f"{c.get('detail', '')}"
                )

        # A sentence that stops mid-word is a truncation, not an explanation.
        if len(output) > 40 and not output.rstrip().endswith((".", "!", "?", '"', ")")):
            reasons.append("the answer was cut off before finishing a sentence")

        return Verdict(ok=not reasons, reasons=reasons)
