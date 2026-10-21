"""HTML fragment endpoints for the HTMX frontend.

The JSON API in loans.py / repayments.py / ai.py / mcp_mode.py / rag_mode.py /
multi_agent.py is the contract other features and tests consume. These
endpoints exist only to return HTML fragments that HTMX swaps into the page,
so the frontend needs no client-side rendering logic.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from html import escape

from flask import Blueprint, make_response, request

from routes.ai import _ask, _fetch_loan_or_error
from routes.mcp_mode import mcp_mode_is_enabled
from services import database_api, mcp_client, multi_agent_client as ma
from services import rag_api
from services.loan_logic import build_schedule, evaluate_eligibility, monthly_payment


ui_bp = Blueprint("ui", __name__, url_prefix="/ui")

LOAN_TYPES = ("PERSONAL", "AUTO", "EDUCATION", "HOME", "BUSINESS")
LOAN_STATUSES = ("PENDING", "APPROVED", "REJECTED", "CANCELLED")
MAX_REVIEWER_CHARS = 60

LOAN_BADGE = {"PENDING": "near", "APPROVED": "ok", "REJECTED": "over", "CANCELLED": ""}
PAYMENT_BADGE = {"PAID": "ok", "PARTIAL": "near", "OVERDUE": "over", "UPCOMING": ""}

MA_RUNNING_STATES = {"created", "planning", "planned", "working",
                     "executed", "reviewing", "revising", "reviewed"}
STATE_BADGE = {"awaiting_human_review": "near", "accepted": "ok",
               "partially_accepted": "ok", "rejected": "over", "failed": "over"}
MA_ERRORS = (ma.MultiAgentDisabled, ma.MultiAgentUnreachable,
             ma.WorkflowRefused, ma.BadServerResponse)


# ---------------------------------------------------------------------------
# Small render helpers
# ---------------------------------------------------------------------------

def _money(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _alert(message, kind="error"):
    return f'<p class="alert alert-{kind}">{escape(str(message))}</p>'


def _int(source, key, default=None):
    raw = str(source.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _badge(text, kind):
    cls = f' badge-{kind}' if kind else ""
    return f'<span class="badge{cls}">{escape(str(text))}</span>'


def _checks_list(checks):
    items = "".join(
        f'<li>{_badge("PASS" if c.get("passed") else "FAIL", "ok" if c.get("passed") else "over")} '
        f'{escape(str(c.get("detail", "")))}</li>'
        for c in checks or []
    )
    return f'<ul class="insight-history">{items}</ul>'


def _paragraphs(text):
    return "".join(
        f"<p>{escape(chunk.strip())}</p>"
        for chunk in str(text or "").split("\n")
        if chunk.strip()
    )


# ---------------------------------------------------------------------------
# Loan list, submit and search
# ---------------------------------------------------------------------------

def _loans_table(loans):
    if not loans:
        return '<p class="empty">No loan applications found.</p>'
    rows = ""
    for loan in loans:
        approved = loan.get("approved_amount")
        rows += f"""
        <tr>
          <td>{escape(str(loan.get("loan_id")))}</td>
          <td>{escape(str(loan.get("customer_id")))}</td>
          <td>{escape(str(loan.get("loan_type")))}</td>
          <td class="num">{_money(loan.get("requested_amount"))}</td>
          <td>{_badge(loan.get("status"), LOAN_BADGE.get(loan.get("status"), ""))}</td>
          <td class="num">{escape(str(loan.get("interest_rate") if loan.get("interest_rate") is not None else "-"))}</td>
          <td class="num">{_money(approved) if approved else "-"}</td>
          <td>{escape(str(loan.get("application_date", ""))[:10])}</td>
        </tr>"""
    return f"""
    <div class="table-scroll">
      <table>
        <thead><tr><th>ID</th><th>Customer</th><th>Type</th><th>Requested</th>
        <th>Status</th><th>Rate %</th><th>Approved</th><th>Date</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


@ui_bp.get("/loans")
def loans_list():
    filters = {
        "customer_id": request.args.get("customer_id"),
        "status": request.args.get("status"),
        "loan_type": request.args.get("loan_type"),
        "q": request.args.get("q"),
    }
    try:
        loans = database_api.search_loans(filters)
    except Exception as exc:
        return _alert(f"Could not load loans: {exc}")
    return _loans_table(loans)


@ui_bp.post("/loans")
def submit_loan():
    form = request.form
    loan_type = str(form.get("loan_type", "")).strip().upper()
    if loan_type not in LOAN_TYPES:
        return _alert(f"loan_type must be one of {', '.join(LOAN_TYPES)}")
    try:
        float(form.get("requested_amount"))
    except (TypeError, ValueError):
        return _alert("Requested amount must be a number.")
    if not str(form.get("customer_id") or "").strip():
        return _alert("Customer ID is required.", "warn")

    loan_data = {
        "customer_id": form.get("customer_id"),
        "loan_type": loan_type,
        "requested_amount": form.get("requested_amount"),
        "loan_purpose": form.get("loan_purpose"),
        "application_date": date.today().isoformat(),
        "status": "PENDING",
        "interest_rate": None,
        "approved_amount": None,
    }
    assessment = evaluate_eligibility(loan_data)
    loan_data["interest_rate"] = assessment.get("proposed_interest_rate")

    try:
        loan = database_api.create_loan(loan_data)
    except Exception as exc:
        return _alert(f"Could not submit application: {exc}")

    e = assessment
    payment = e.get("estimated_monthly_payment")
    rate = e.get("proposed_interest_rate")
    notice = (
        f'<p><b>Application #{escape(str(loan["loan_id"]))} submitted (PENDING).</b><br>'
        f'Eligible now: {"Yes" if e["eligible"] else "No"} | '
        f'Est. payment: {_money(payment) if payment is not None else "-"} '
        f'@ {escape(str(rate if rate is not None else "-"))}%</p>'
        + _checks_list(e.get("checks"))
    )
    return _alert("Application submitted.", "success") + notice


# ---------------------------------------------------------------------------
# Loan details, eligibility, decision, delete
# ---------------------------------------------------------------------------

def _repayments_table(repayments, upcoming=False):
    if not repayments:
        return '<p class="empty">No repayments found.</p>'
    head = "<th>ID</th><th>Loan</th>"
    if upcoming:
        head += "<th>Customer</th><th>Type</th>"
    head += "<th>Due</th><th>Payment</th><th>Principal</th><th>Interest</th><th>Paid</th><th>Status</th>"
    if upcoming:
        head += "<th>Days</th>"
    rows = ""
    for r in repayments:
        row = f"<td>{escape(str(r.get('repayment_id')))}</td><td>{escape(str(r.get('loan_id')))}</td>"
        if upcoming:
            row += (f"<td>{escape(str(r.get('customer_id', '-')))}</td>"
                    f"<td>{escape(str(r.get('loan_type', '-')))}</td>")
        row += (f"<td>{escape(str(r.get('due_date', ''))[:10])}</td>"
                f'<td class="num">{_money(r.get("payment_amount"))}</td>'
                f'<td class="num">{_money(r.get("principal_amount"))}</td>'
                f'<td class="num">{_money(r.get("interest_amount"))}</td>'
                f'<td class="num">{_money(r.get("amount_paid"))}</td>')
        status = r.get("payment_status")
        row += f"<td>{_badge(status, PAYMENT_BADGE.get(status, ''))}</td>"
        if upcoming:
            row += f"<td>{escape(str(r.get('days_until_due', '-')))}</td>"
        rows += f"<tr>{row}</tr>"
    return f"""
    <div class="table-scroll">
      <table>
        <thead><tr>{head}</tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""


def _eligibility_html(assessment):
    e = assessment
    payment = e.get("estimated_monthly_payment")
    rate = e.get("proposed_interest_rate")
    term = e.get("proposed_term_months")
    return (
        f'<p><b>Eligible: {"Yes" if e.get("eligible") else "No"}</b> | '
        f'Rate {escape(str(rate if rate is not None else "-"))}% | '
        f'Term {escape(str(term if term is not None else "-"))} mo | '
        f'Payment {_money(payment) if payment is not None else "-"}</p>'
        + _checks_list(e.get("checks"))
    )


def _loan_detail(loan):
    loan_id = loan.get("loan_id")
    status = loan.get("status")
    approved = loan.get("approved_amount")

    actions = (
        f'<button type="button" class="btn btn-secondary btn-small" '
        f'hx-get="/ui/loans/{loan_id}/eligibility" hx-target="#detail-panel" '
        f'hx-swap="innerHTML">Check Eligibility</button>'
    )
    if status == "PENDING":
        actions += (
            f'<button type="button" class="btn btn-small" '
            f'hx-post="/ui/loans/{loan_id}/decision" hx-vals=\'{{"action": "APPROVE"}}\' '
            f'hx-target="#detail-panel" hx-swap="innerHTML" '
            f'hx-confirm="Approve loan #{loan_id}?">Approve</button>'
            f'<button type="button" class="btn btn-secondary btn-small" '
            f'hx-post="/ui/loans/{loan_id}/decision" hx-vals=\'{{"action": "REJECT"}}\' '
            f'hx-target="#detail-panel" hx-swap="innerHTML" '
            f'hx-confirm="Reject loan #{loan_id}?">Reject</button>'
        )
    if status != "APPROVED":
        actions += (
            f'<button type="button" class="btn btn-danger btn-small" '
            f'hx-delete="/ui/loans/{loan_id}" hx-target="#detail-panel" '
            f'hx-swap="innerHTML" hx-confirm="Delete loan #{loan_id} and its repayments?">Delete</button>'
        )

    return f"""
    <div>
      <p><b>Loan #{escape(str(loan_id))}</b> - {escape(str(loan.get("loan_type")))} - {_badge(status, LOAN_BADGE.get(status, ""))}<br>
       Customer {escape(str(loan.get("customer_id")))} |
       Requested {_money(loan.get("requested_amount"))} |
       Approved {_money(approved) if approved else "-"} |
       Rate {escape(str(loan.get("interest_rate") if loan.get("interest_rate") is not None else "-"))}% |
       Term {escape(str(loan.get("term_months") if loan.get("term_months") is not None else "-"))} months<br>
       Purpose: {escape(str(loan.get("loan_purpose") or "-"))} |
       Applied: {escape(str(loan.get("application_date", ""))[:10])}</p>
      <div class="form-actions">{actions}</div>
      {_repayments_table(loan.get("repayments"))}
    </div>"""


@ui_bp.get("/loans/detail")
def loan_detail():
    loan_id = _int(request.args, "loan_id")
    if loan_id is None:
        return _alert("Enter a loan ID first.", "warn")
    try:
        response = database_api.get_loan_response(loan_id)
    except Exception as exc:
        return _alert(f"Could not load loan: {exc}")
    if response.status_code == 404:
        return _alert("Loan application not found.", "warn")
    return _loan_detail(response.json())


@ui_bp.get("/loans/<int:loan_id>/eligibility")
def loan_eligibility(loan_id):
    try:
        response = database_api.get_loan_response(loan_id)
    except Exception as exc:
        return _alert(f"Could not load loan: {exc}")
    if response.status_code == 404:
        return _alert("Loan application not found.", "warn")
    loan = response.json()
    return _eligibility_html(evaluate_eligibility(loan))


@ui_bp.post("/loans/<int:loan_id>/decision")
def loan_decision(loan_id):
    action = str(request.form.get("action", "")).strip().upper()
    if action not in ("APPROVE", "REJECT"):
        return _alert('action must be "APPROVE" or "REJECT".')

    try:
        response = database_api.get_loan_response(loan_id)
        if response.status_code == 404:
            return _alert("Loan application not found.", "warn")
        loan = response.json()

        if loan["status"] != "PENDING":
            return _alert(f"Loan is already {loan['status']}.", "warn")

        assessment = evaluate_eligibility(loan)

        if action == "REJECT":
            updated = database_api.update_loan(loan_id, {"status": "REJECTED"})
            notice = _alert("Loan rejected.", "success")
            return notice + _loan_detail(updated)

        if not assessment["eligible"]:
            return _alert("Loan is not eligible; use Reject instead.", "warn") + _eligibility_html(assessment)

        approved_amount = min(float(loan["requested_amount"]), assessment["max_allowed_amount"])
        rate = assessment["proposed_interest_rate"]
        term = assessment["proposed_term_months"]

        start = date.fromisoformat(str(loan["application_date"])[:10])
        schedule = [
            {**row, "loan_id": loan_id}
            for row in build_schedule(approved_amount, rate, term, start)
        ]

        created_repayments = database_api.create_repayments(schedule)
        try:
            updated = database_api.update_loan(
                loan_id,
                {
                    "status": "APPROVED",
                    "interest_rate": rate,
                    "approved_amount": approved_amount,
                },
            )
        except Exception:  # noqa: S110  # rollback should keep the database consistent even when update fails
            for repayment in created_repayments:
                try:
                    database_api.delete_repayment(repayment["repayment_id"])
                except Exception:  # noqa: S110  # cleanup is best-effort while rolling back a failed loan approval
                    pass
            raise
    except Exception as exc:
        return _alert(f"Could not record the decision: {exc}")

    notice = (
        f'<p><b>Approved.</b> {len(created_repayments)} repayments created, '
        f'first due {escape(str(created_repayments[0]["due_date"])[:10])}, '
        f'monthly {_money(created_repayments[0]["payment_amount"])}.</p>'
    )
    return _alert("Loan approved.", "success") + notice + _loan_detail(updated)


@ui_bp.delete("/loans/<int:loan_id>")
def loan_delete(loan_id):
    try:
        existing = database_api.get_loan_response(loan_id)
        if existing.status_code == 404:
            return _alert("Loan application not found.", "warn")
        loan = existing.json()
        if loan["status"] == "APPROVED":
            return _alert("Approved loans cannot be deleted. Set status to CANCELLED first.", "warn")
        database_api.delete_loan(loan_id)
    except Exception as exc:
        return _alert(f"Could not delete loan: {exc}")
    return _alert(f"Deleted loan {loan_id} and its repayments.", "success")


# ---------------------------------------------------------------------------
# Repayments
# ---------------------------------------------------------------------------

@ui_bp.get("/repayments")
def repayments_list():
    try:
        repayments = database_api.search_repayments()
    except Exception as exc:
        return _alert(f"Could not load repayments: {exc}")
    return _repayments_table(repayments)


@ui_bp.get("/repayments/upcoming")
def repayments_upcoming():
    days = _int(request.args, "days", 30)
    horizon = (date.today() + timedelta(days=days)).isoformat()
    try:
        repayments = database_api.search_repayments({"due_before": horizon, "unpaid": "true"})
        loans = {loan["loan_id"]: loan for loan in database_api.search_loans()}
    except Exception as exc:
        return _alert(f"Could not load repayments: {exc}")

    results = []
    for repayment in repayments:
        entry = dict(repayment)
        loan = loans.get(repayment["loan_id"])
        if loan:
            entry["customer_id"] = loan["customer_id"]
            entry["loan_type"] = loan["loan_type"]
        due = date.fromisoformat(str(repayment["due_date"])[:10])
        entry["days_until_due"] = (due - date.today()).days
        results.append(entry)
    return _repayments_table(results, upcoming=True)


@ui_bp.put("/repayments/update")
def repayment_update():
    form = request.form
    repayment_id = _int(form, "repayment_id")
    if repayment_id is None:
        return _alert("Enter a repayment ID first.", "warn")

    updates = {}
    if str(form.get("amount_paid") or "").strip():
        updates["amount_paid"] = form.get("amount_paid")
    if str(form.get("payment_status") or "").strip():
        updates["payment_status"] = form.get("payment_status")
    if not updates:
        return _alert("Nothing to update: enter an amount paid or a status.", "warn")

    try:
        existing = database_api.get_repayment(repayment_id)
    except Exception as exc:
        return _alert(f"Could not load repayment: {exc}")

    if updates.get("amount_paid") is not None and updates.get("payment_status") is None:
        paid = float(updates["amount_paid"])
        if paid >= float(existing["payment_amount"]):
            updates["payment_status"] = "PAID"
            updates.setdefault("payment_date", date.today().isoformat())
        elif paid > 0:
            updates["payment_status"] = "PARTIAL"

    try:
        updated = database_api.update_repayment(repayment_id, updates)
    except Exception as exc:
        return _alert(f"Could not update repayment: {exc}")

    notice = (
        f'<p>Updated repayment #{escape(str(updated["repayment_id"]))}: '
        f'paid {_money(updated["amount_paid"])} of {_money(updated["payment_amount"])} - '
        f'{_badge(updated["payment_status"], PAYMENT_BADGE.get(updated["payment_status"], ""))}</p>'
    )
    refreshed = database_api.search_repayments()
    return _alert("Repayment updated.", "success") + notice + _repayments_table(refreshed)


# ---------------------------------------------------------------------------
# AI Mode: explanations and repayment comparison
# ---------------------------------------------------------------------------

def _explanation_card(title, explanation):
    return f"""
    <article class="insight-card">
      <h3>{escape(title)}</h3>
      {_paragraphs(explanation)}
    </article>"""


@ui_bp.get("/ai/explain-eligibility")
def ai_explain_eligibility():
    loan_id = _int(request.args, "loan_id")
    if loan_id is None:
        return _alert("Enter a loan ID first.", "warn")
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return _alert("Loan application not found.", "warn")
        assessment = evaluate_eligibility(loan)
        explanation = _ask(
            "explanation_system.txt",
            "eligibility_task.txt",
            json.dumps({"loan": loan, "assessment": assessment}),
        )
    except Exception as exc:
        return _alert(f"AI request failed: {exc}")
    return _explanation_card(f"Eligibility for loan #{loan_id}", explanation)


@ui_bp.get("/ai/explain-decision")
def ai_explain_decision():
    loan_id = _int(request.args, "loan_id")
    if loan_id is None:
        return _alert("Enter a loan ID first.", "warn")
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return _alert("Loan application not found.", "warn")
        status = loan["status"]
        if status not in ("APPROVED", "REJECTED"):
            return _alert(
                f"Loan has not been decided yet (status {status}). "
                "Approve or reject it on the Normal tab first.", "warn")
        assessment = evaluate_eligibility(loan)
        explanation = _ask(
            "explanation_system.txt",
            "decision_task.txt",
            json.dumps({"loan": loan, "assessment": assessment}),
        )
    except Exception as exc:
        return _alert(f"AI request failed: {exc}")
    return _explanation_card(f"Decision for loan #{loan_id}: {status}", explanation)


@ui_bp.get("/ai/explain-repayments")
def ai_explain_repayments():
    loan_id = _int(request.args, "loan_id")
    if loan_id is None:
        return _alert("Enter a loan ID first.", "warn")
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return _alert("Loan application not found.", "warn")
        repayments = database_api.search_repayments({"loan_id": loan_id})
        explanation = _ask(
            "explanation_system.txt",
            "repayment_task.txt",
            json.dumps({"loan": loan, "repayments": repayments}),
        )
    except Exception as exc:
        return _alert(f"AI request failed: {exc}")
    return _explanation_card(f"Repayments for loan #{loan_id}", explanation)


@ui_bp.post("/ai/repayment-options")
def ai_compare():
    form = request.form
    loan = None
    loan_id = _int(form, "loan_id")
    if loan_id is not None:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return _alert("Loan application not found.", "warn")

    try:
        amount = float(form.get("amount") or (loan or {}).get("approved_amount")
                       or (loan or {}).get("requested_amount"))
        rate = float(form.get("interest_rate") or (loan or {}).get("interest_rate") or 8.5)
        income = form.get("monthly_income") or (loan or {}).get("monthly_income")
        terms = [int(t) for t in str(form.get("terms") or "").split(",") if t.strip()]
        terms = (terms or [12, 24, 36, 48, 60])[:6]
    except (TypeError, ValueError) as exc:
        return _alert(f"Invalid input: {exc}")

    rows = ""
    options = []
    for term in terms:
        payment = round(monthly_payment(amount, rate, term), 2)
        total_paid = round(payment * term, 2)
        option = {
            "term_months": term,
            "monthly_payment": payment,
            "total_interest": round(total_paid - amount, 2),
            "total_repaid": total_paid,
        }
        if income:
            try:
                option["payment_share_of_income"] = round(payment / float(income) * 100, 1)
            except (TypeError, ValueError):
                pass
        options.append(option)
        rows += (
            f"<tr><td>{term} mo</td><td class=\"num\">{_money(payment)}</td>"
            f'<td class="num">{_money(option["total_interest"])}</td>'
            f'<td class="num">{escape(str(option.get("payment_share_of_income", "-")))}</td></tr>'
        )

    payload = {"amount_financed": amount, "annual_interest_rate_pct": rate, "options": options}
    if income:
        payload["monthly_income"] = income

    try:
        explanation = _ask(
            "explanation_system.txt",
            "comparison_task.txt",
            json.dumps(payload),
            max_tokens=1500,
        )
    except Exception as exc:
        return _alert(f"AI request failed: {exc}")

    return f"""
    <article class="insight-card">
      <h3>Repayment options for {_money(amount)} at {escape(str(rate))}%</h3>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Term</th><th>Monthly</th><th>Total Interest</th><th>% of Income</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <h4>AI recommendation</h4>
      {_paragraphs(explanation)}
    </article>"""


# ---------------------------------------------------------------------------
# MCP Mode: loans_list through the shared MCP server
# ---------------------------------------------------------------------------

@ui_bp.post("/mcp/loans-list")
def mcp_loans_list():
    if not mcp_mode_is_enabled(request):
        return _alert("MCP Mode is OFF. Enable MCP Mode to run MCP tools.", "warn")

    customer_id = _int(request.form, "customer_id")
    if customer_id is None or customer_id < 1:
        return _alert("customer_id must be a positive integer.", "warn")
    arguments = {"customer_id": customer_id}
    status = str(request.form.get("status") or "").strip().upper()
    if status:
        arguments["status"] = status

    try:
        result = mcp_client.call_tool("loans_list", arguments)
    except mcp_client.MCPUnavailable as exc:
        return _alert(str(exc))

    if result["is_error"]:
        return _alert(f"The MCP tool returned an error: {result['text'] or 'MCP tool failed.'}", "warn")

    data = result["structured"] or {}
    loans = data.get("loans") or []
    rows = "".join(
        f"<tr><td>{escape(str(l.get('loan_id')))}</td>"
        f"<td>{escape(str(l.get('loan_type')))}</td>"
        f'<td class="num">{_money(l.get("requested_amount"))}</td>'
        f"<td>{_badge(l.get('status'), LOAN_BADGE.get(l.get('status'), ''))}</td></tr>"
        for l in loans
    )
    table = (
        f"""<div class="table-scroll"><table>
        <thead><tr><th>Loan ID</th><th>Type</th><th>Requested</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody></table></div>"""
        if loans else '<p class="empty">No loans found for this customer.</p>'
    )
    source = data.get("source") or {}
    status_filter = data.get("status_filter")
    return f"""
    <article class="insight-card">
      <h3>MCP Tool: loans_list</h3>
      {table}
      <p class="muted">{escape(str(data.get("loan_count", 0)))} loans for customer
      {escape(str(data.get("customer_id")))}
      {f"filtered by status {escape(str(status_filter))}" if status_filter else ""}
      &middot; source: {escape(str(source.get("feature", "loans")))}
      {escape(str(source.get("endpoint", "")))}</p>
    </article>"""


# ---------------------------------------------------------------------------
# RAG Mode: retrieve evidence and grounded answers
# ---------------------------------------------------------------------------

CONFIDENCE_BADGE = {"High": "ok", "Medium": "near", "Low": "over"}


@ui_bp.post("/rag/retrieve")
def rag_retrieve():
    if not rag_api.rag_mode_is_enabled(request):
        return _alert("RAG Mode is OFF. Enable RAG Mode to run RAG tools.", "warn")
    query = str(request.form.get("query") or "").strip()
    if not query:
        return _alert("Type a retrieval phrase first.", "warn")
    try:
        payload = rag_api.call_rag_service("/retrieve", {"query": query, "k": 5, "caller": "loans"})
    except Exception as exc:
        return _alert(f"RAG request failed: {exc}")

    evidence = payload.get("evidence") or []
    rows = "".join(
        f"<tr><td>{escape(str(e.get('rank')))}</td>"
        f"<td>{escape(str(e.get('chunk_id')))}</td>"
        f"<td>{escape(str(e.get('title')))}</td>"
        f"<td class=\"num\">{escape(str(e.get('relevance') if e.get('relevance') is not None else '-'))}</td>"
        f"<td>T{escape(str(e.get('authority_tier', '')))}</td>"
        f"<td><pre>{escape(str(e.get('text')))}</pre></td></tr>"
        for e in evidence
    )
    table = (
        f"""<div class="table-scroll"><table>
        <thead><tr><th>#</th><th>Chunk</th><th>Source</th><th>Relevance</th><th>Tier</th><th>Text</th></tr></thead>
        <tbody>{rows}</tbody></table></div>"""
        if evidence else '<p class="empty">No evidence retrieved.</p>'
    )
    return f"""
    <article class="insight-card">
      <h3>RAG Tool: retrieve_context</h3>
      <p class="muted">{escape(str(payload.get('retrieved_count', 0)))} retrieved,
      {escape(str(payload.get('relevant_count', 0)))} relevant
      &middot; mode {escape(str(payload.get('retrieval_mode', '-')))}</p>
      {table}
    </article>"""


@ui_bp.post("/rag/answer")
def rag_answer():
    if not rag_api.rag_mode_is_enabled(request):
        return _alert("RAG Mode is OFF. Enable RAG Mode to run RAG tools.", "warn")
    query = str(request.form.get("query") or "").strip()
    if not query:
        return _alert("Type a question first.", "warn")
    try:
        payload = rag_api.call_rag_service("/query", {"query": query, "k": 5, "caller": "loans"})
    except Exception as exc:
        return _alert(f"RAG request failed: {exc}")

    confidence = payload.get("confidence_category")
    citations = "".join(
        f"""<li><div class="history-head">
        <span class="chip">{escape(str(c.get('chunk_id', '')))}</span>
        <span class="muted">{escape(str(c.get('title', '')))}
        {f"({escape(str(c.get('source_id')))} )" if c.get("source_id") else ""}</span>
        </div></li>"""
        for c in payload.get("citations") or []
    )
    summary = payload.get("retrieval_summary") or {}
    model = (payload.get("generation") or {}).get("model") or "-"
    return f"""
    <article class="insight-card">
      <h3>RAG Tool: answer_question {_badge(f"Confidence: {confidence}" if confidence else "Confidence: Unknown", CONFIDENCE_BADGE.get(confidence, ""))}</h3>
      <p><b>Question:</b> {escape(str(payload.get('query', '')))}</p>
      <p><b>Answer:</b> {escape(str(payload.get('answer', '')))}</p>
      <h4 class="muted">Citations ({len(payload.get('citations') or [])})</h4>
      <ul class="insight-history">{citations}</ul>
      <p class="muted">{escape(str(summary.get('relevant_count', 0)))} relevant chunks
      &middot; insufficient_context: {"yes" if payload.get("insufficient_context") else "no"}
      &middot; model {escape(str(model))}</p>
    </article>"""


# ---------------------------------------------------------------------------
# Multi-Agent Mode: planner -> worker -> reviewer workflows
# ---------------------------------------------------------------------------

def _ma_alert(exc):
    if isinstance(exc, ma.WorkflowRefused):
        kind = "warn" if exc.status < 500 else "error"
        return _alert(f"Multi-Agent Server (HTTP {exc.status}): {str(exc).rstrip('.')}.", kind)
    return _alert(str(exc).rstrip("."), "warn")


def _temporary(exc):
    """A server that is down may answer later; a broken reply will not."""
    return isinstance(exc, ma.MultiAgentUnreachable)


def _stage_badges(record):
    out = []
    for role, label in (("planner", "Planner"), ("worker", "Worker"),
                        ("reviewer", "Reviewer"), ("human", "Human")):
        stage = next(
            (s for s in reversed(record.get("stages") or []) if s.get("role") == role),
            None,
        )
        if stage:
            status = str(stage.get("status", "pending"))
            cls = "ok" if status == "completed" else ("over" if status in ("failed", "timed_out") else "near")
            text = f"{label} {status.replace('_', ' ')}"
            if stage.get("attempt", 1) > 1:
                text += f" #{stage['attempt']}"
            if stage.get("fallback"):
                text += " fallback"
            if stage.get("duration_seconds") is not None:
                text += f" {stage['duration_seconds']}s"
        elif role == "human":
            if record.get("decision"):
                cls, text = "ok", "Human decided"
            elif record.get("state") == "awaiting_human_review":
                cls, text = "near", "Human awaiting decision"
            else:
                cls, text = "near", "Human pending"
        else:
            cls, text = "near", f"{label} pending"
        out.append(f'<span class="badge badge-{cls}">{escape(text)}</span>')
    return " ".join(out)


def _list(items):
    if not items:
        return ""
    return "<ul>" + "".join(f'<li class="muted">{escape(str(i))}</li>' for i in items) + "</ul>"


def _plan_html(plan):
    if not isinstance(plan, dict) or not (plan.get("objective") or plan.get("tasks")):
        return ""
    tasks = ""
    for t in plan.get("tasks") or []:
        title = t.get("title") or t.get("instruction") or t.get("endpoint") or t.get("id") or ""
        if t.get("kind") == "api":
            tasks += (f'<li><span class="chip">{escape(str(t.get("id") or ""))}</span> '
                      f'<code>{escape(str(t.get("endpoint") or ""))}</code> '
                      f'<span class="muted">{escape(str(title))}</span></li>')
        else:
            tasks += (f'<li><span class="chip">{escape(str(t.get("id") or ""))}</span> '
                      f'{escape(str(title))}</li>')
    return f"""
      <section class="ma-section">
        <h4>Plan</h4>
        <p>{escape(str(plan.get("objective") or ""))}</p>
        <ul class="insight-history">{tasks}</ul>
      </section>"""


def _result_html(result):
    if not isinstance(result, dict):
        return ""
    rows = ""
    for e in result.get("evidence") or []:
        ok = e.get("status") == "ok"
        detail = (f"HTTP {e.get('http_status')} {e.get('duration_seconds')}s"
                  if ok else str(e.get("error", "")))
        rows += (f'<tr><td><span class="chip">{escape(str(e.get("task_id")))}</span></td>'
                 f'<td><code>{escape(str(e.get("endpoint")))}</code></td>'
                 f'<td>{_badge(e.get("status"), "ok" if ok else "over")}</td>'
                 f'<td class="muted">{escape(detail)}</td></tr>')
    evidence = ""
    if rows:
        evidence = f"""
        <h4>Evidence</h4>
        <div class="table-scroll"><table>
          <thead><tr><th>Task</th><th>Endpoint</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>{rows}</tbody></table></div>"""
    findings = "".join(
        f'<li><span class="chip">{escape(str(f.get("task_id")))}</span> '
        f'{escape(str(f.get("statement")))} '
        f'<span class="muted">evidence {escape(", ".join(f.get("evidence") or []))}</span></li>'
        for f in result.get("findings") or []
    )
    findings_html = f'<h4>Findings</h4><ul class="insight-history">{findings}</ul>' if findings else ""
    answer = ""
    if result.get("answer") is not None:
        answer = f'<h4>Worker answer</h4>{_paragraphs(result.get("answer"))}'
    gaps = f'<p class="muted">Gaps</p>{_list(result.get("gaps"))}' if result.get("gaps") else ""
    if not (evidence or findings_html or answer or gaps):
        return ""
    return f"<section class=\"ma-section\">{evidence}{findings_html}{answer}{gaps}</section>"


def _review_html(review):
    if not isinstance(review, dict):
        return ""
    verdict = str(review.get("verdict", ""))
    cls = "ok" if verdict.lower() in ("accept", "pass") else "near"
    heading = "<h4>Review" + (f' <span class="badge badge-{cls}">{escape(verdict)}</span>' if verdict else "") + "</h4>"
    summary = f"<p>{escape(str(review.get('summary') or ''))}</p>" if review.get("summary") else ""
    risks = f'<p class="muted">Risks</p>{_list(review.get("risks"))}' if review.get("risks") else ""
    revisions = (f'<p class="muted">Revision notes</p>{_list(review.get("revision_notes"))}'
                 if review.get("revision_notes") else "")
    defects = "".join(
        f'<li>{_badge(d.get("severity", "Issue"), "over")} '
        f'{escape(str(d.get("note") or d.get("about") or ""))}</li>'
        for d in review.get("defects") or []
    )
    defects_html = f'<p class="muted">Defects</p><ul class="insight-history">{defects}</ul>' if defects else ""
    if not (verdict or summary or risks or revisions or defects_html):
        return ""
    return f'<section class="ma-section">{heading}{summary}{risks}{revisions}{defects_html}</section>'


def _final_html(final):
    if not isinstance(final, dict):
        return ""
    if not final.get("released"):
        text = final.get("correction_note") or "The response was withheld."
        return (f'<section class="ma-section"><h4>Final response '
                f'<span class="badge badge-over">withheld</span></h4>'
                f'<p>{escape(str(text))}</p></section>')
    text = final.get("answer") or "No response text was returned."
    return (f'<section class="ma-section ma-final"><h4>Final response '
            f'<span class="badge badge-ok">released</span></h4>'
            f'{_paragraphs(text)}</section>')


def _decision_block(workflow_id):
    """Reviewer name, note and three buttons; a refused decision shows its
    reason in the message slot so the typed fields stay as they are."""
    workflow_id = escape(str(workflow_id))
    buttons = "".join(
        f'<button type="button" class="btn{" btn-danger" if value == "reject" else ""}" '
        f'hx-post="/ui/multi-agent/workflows/{workflow_id}/decision" '
        f"hx-vals='{json.dumps({'decision': value})}' "
        f'hx-include="closest .ma-decision" hx-target="#ma-msg-{workflow_id}" '
        f'hx-swap="innerHTML" hx-sync="closest .ma-decision:drop" '
        f'hx-disabled-elt="this">{label}</button>'
        for value, label in (("accept", "Accept"),
                             ("partially_accept", "Partially accept"),
                             ("reject", "Reject")))
    return f"""
      <section class="ma-section ma-decision">
        <h4>Human workflow decision</h4>
        <p class="muted">Review the agent result and choose whether to accept, partially accept, or reject it.</p>
        <div class="row">
          <div>
            <label for="ma-reviewer-{workflow_id}">Reviewer</label>
            <input id="ma-reviewer-{workflow_id}" name="reviewer" type="text"
                   maxlength="{MAX_REVIEWER_CHARS}" placeholder="Your name (optional)">
          </div>
          <div class="grow">
            <label for="ma-note-{workflow_id}">Decision note</label>
            <textarea id="ma-note-{workflow_id}" name="note" rows="2"
                      maxlength="{ma.MAX_NOTE_CHARS}" placeholder="Required for Partially accept"></textarea>
          </div>
        </div>
        <div id="ma-msg-{workflow_id}" class="ma-message"></div>
        <div class="form-actions">{buttons}</div>
      </section>"""


def _workflow_card(full, message=""):
    """The whole workflow as one swappable card; it polls itself while it runs."""
    workflow_id = escape(str(full.get("workflow_id", "")))
    state = str(full.get("state", ""))
    running = state in MA_RUNNING_STATES
    poll = (f' hx-get="/ui/multi-agent/workflows/{workflow_id}" '
            f'hx-trigger="every 2s" hx-swap="outerHTML"' if running else "")
    context = full.get("context") or {}
    head = f'Customer {escape(str(context.get("customer_id", "")))}'
    error = f'<p class="alert alert-error">{escape(str(full.get("error")))}</p>' if full.get("error") else ""
    body = (_plan_html(full.get("plan")) + _result_html(full.get("result"))
            + _review_html(full.get("review")))
    if state == "awaiting_human_review" and not full.get("decision"):
        body += _decision_block(workflow_id)
    body += _final_html(full.get("final_response"))
    revisions = (f' <span class="muted">revisions {escape(str(full.get("revisions")))}</span>'
                 if full.get("revisions") else "")
    return f"""
    <article class="insight-card ma-card" id="ma-{workflow_id}"{poll}>
      <div class="history-head">
        <span class="chip">{workflow_id}</span>
        <span class="badge badge-{STATE_BADGE.get(state, "near")}">{escape(state.replace("_", " ") or "unknown")}</span>{revisions}
        <span class="htmx-indicator muted">{"Running" if running else ""}</span>
      </div>
      <p class="muted">{head} &middot; {escape(str(full.get("request") or ""))}</p>
      <p class="muted">{_stage_badges(full)}</p>
      {message}{error}{body}
    </article>"""


def _retry_card(workflow_id, exc):
    """A down or failing server keeps the card and its polling, so the
    workflow is not lost from the page."""
    workflow_id = escape(str(workflow_id))
    return f"""
    <article class="insight-card ma-card" id="ma-{workflow_id}"
             hx-get="/ui/multi-agent/workflows/{workflow_id}" hx-trigger="every 5s" hx-swap="outerHTML">
      <div class="history-head"><span class="chip">{workflow_id}</span><span class="badge badge-near">retrying</span></div>
      <p class="alert alert-warn">{escape(str(exc).rstrip('.'))}. Checking again.</p>
    </article>"""


def _load_card(workflow_id, message=""):
    try:
        full = ma.workflow(workflow_id)
    except MA_ERRORS as exc:
        return _retry_card(workflow_id, exc) if _temporary(exc) else _ma_alert(exc)
    return _workflow_card(full, message)


def _card_response(workflow_id, message=""):
    """The card as a response; when it has stopped running the history list
    is told to refresh, so the final state shows up right."""
    response = make_response(_load_card(workflow_id, message))
    body = response.get_data(as_text=True)
    if 'hx-trigger="every' not in body and f'id="ma-{escape(str(workflow_id))}"' in body:
        response.headers["HX-Trigger"] = "ma-updated"
    return response


def _replace_card(workflow_id, message, trigger):
    """The whole card instead of the message slot the button targeted."""
    response = make_response(_load_card(workflow_id, message))
    response.headers["HX-Retarget"] = f"#ma-{escape(str(workflow_id))}"
    response.headers["HX-Reswap"] = "outerHTML"
    response.headers["HX-Trigger"] = trigger
    return response


@ui_bp.get("/multi-agent/status")
def ma_status():
    if not ma.enabled():
        return '<span class="badge badge-near">Inactive</span> <code>MULTI_AGENT_ENABLED=false</code>'
    url = f"<code>{escape(ma.server_url())}</code>"
    try:
        count = len(ma.history())
    except MA_ERRORS as exc:
        return (f'<span class="badge badge-over">Unreachable</span> {url} &middot; '
                f'{escape(str(exc).rstrip("."))}')
    return f'<span class="badge badge-ok">Reachable</span> {url} &middot; {count} loans workflows'


@ui_bp.post("/multi-agent/workflows")
def ma_start():
    text = str(request.form.get("request") or "").strip()
    if not text:
        return _alert("Type the request first.", "warn")
    if len(text) > ma.MAX_REQUEST_CHARS:
        return _alert(f"Requests are limited to {ma.MAX_REQUEST_CHARS} characters.", "warn")
    customer_id = _int(request.form, "customer_id", 1) or 1
    try:
        summary = ma.start(text, customer_id)
    except MA_ERRORS as exc:
        return _ma_alert(exc)
    response = make_response(_load_card(summary["workflow_id"]))
    response.headers["HX-Trigger"] = "ma-started"           # the history list refreshes itself
    return response


@ui_bp.get("/multi-agent/workflows/last")
def ma_last():
    """The newest loans workflow, which is what the status button wants."""
    try:
        history = ma.history()
    except MA_ERRORS as exc:
        return _ma_alert(exc)
    if not history:
        return _alert("No loans workflows yet: start one from this tab.", "warn")
    return _card_response(history[0]["workflow_id"])


@ui_bp.get("/multi-agent/workflows/<workflow_id>")
def ma_workflow(workflow_id):
    """The card: polled every 2s while the stages run, then the gate, then the answer."""
    return _card_response(workflow_id)


@ui_bp.post("/multi-agent/workflows/<workflow_id>/decision")
def ma_decision(workflow_id):
    decision = str(request.form.get("decision") or "").strip()
    note = str(request.form.get("note") or "").strip()
    reviewer = str(request.form.get("reviewer") or "").strip()[:MAX_REVIEWER_CHARS]
    try:
        ma.decide(workflow_id, decision, note, reviewer)
    except ma.WorkflowRefused as exc:
        if exc.status == 409:                           # decided elsewhere: show the card as it is now
            return _replace_card(workflow_id, _alert(f"{str(exc).rstrip('.')}.", "warn"), "ma-updated")
        return _alert(f"{str(exc).rstrip('.')}. Try again.", "warn")
    except MA_ERRORS as exc:
        return _ma_alert(exc)
    return _replace_card(workflow_id, "", "ma-decided")


@ui_bp.get("/multi-agent/history")
def ma_history():
    """This feature's latest workflows, newest first; Open loads one into the panel."""
    try:
        workflows = ma.history()
    except MA_ERRORS as exc:
        return f'<p class="empty">{escape(str(exc).rstrip("."))}.</p>'
    if not workflows:
        return '<p class="empty">No loans workflows yet.</p>'
    items = ""
    for w in workflows:
        workflow_id = escape(str(w.get("workflow_id")))
        context = w.get("context") or {}
        state = str(w.get("state", ""))
        items += f"""
        <li>
          <div class="history-head">
            <span class="chip">{workflow_id}</span>
            <span class="badge badge-{STATE_BADGE.get(state, "near")}">{escape(state.replace("_", " "))}</span>
            <span class="muted">{escape(str(w.get("created_at", "")))}</span>
            <button type="button" class="btn btn-secondary btn-small"
                    hx-get="/ui/multi-agent/workflows/{workflow_id}"
                    hx-target="#ma-panel" hx-swap="innerHTML">Open</button>
          </div>
          <p class="muted">Customer {escape(str(context.get("customer_id", "")))} &middot;
          {escape(str(w.get("request", "")))}</p>
        </li>"""
    return f'<ul class="insight-history">{items}</ul>'
