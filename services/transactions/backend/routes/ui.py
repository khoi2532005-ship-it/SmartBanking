"""HTML fragment endpoints for the Transactions UI."""

import json
import re
from datetime import date
from html import escape

from flask import Blueprint, request

from routes.agents import decided_by, operator_check
from services import mcp_client, multi_agent_client, rag_client

ui_bp = Blueprint("ui", __name__, url_prefix="/ui")


def _current_period():
    today = date.today()
    return today.month, today.year


def _period(source):
    """Month and year from the panel's inputs, or the current month if either is missing or out of range."""
    month, year = _current_period()
    try:
        chosen_month, chosen_year = int(source.get("month")), int(source.get("year"))
    except (TypeError, ValueError):
        return month, year
    if 1 <= chosen_month <= 12 and 2000 <= chosen_year <= 2100:
        return chosen_month, chosen_year
    return month, year


def _customer(source):
    try:
        return int(source.get("customer_id") or 1)
    except (TypeError, ValueError):
        return 1


def _money(value):
    return f"${float(value):,.2f}"


def _alert(message, kind="error"):
    return f'<p class="alert alert-{kind}">{escape(str(message))}</p>'


def _integration_alert(exc):
    if isinstance(
        exc,
        (
            mcp_client.MCPDisabled,
            rag_client.RAGDisabled,
            multi_agent_client.MultiAgentDisabled,
        ),
    ):
        return _alert(f"{exc} - this control is retained but inactive here.", "warn")
    return _alert(str(exc))


def _status_line(label, info, detail=""):
    url = f'<code>{escape(str(info.get("url", "")))}</code>'
    if not info.get("enabled"):
        return (
            f'<span class="badge badge-near">Inactive</span> {label} integration is '
            f'{escape(str(info.get("note", "disabled")))}: the controls below are retained '
            f'but make no network call.'
        )
    if info.get("reachable"):
        return (
            f'<span class="badge badge-ok">Reachable</span> {label} at {url}. {detail}'
        )
    return (
        f'<span class="badge badge-over">Unreachable</span> {label} at {url}: '
        f'{escape(str(info.get("error", "no response")))}'
    )


@ui_bp.get("/mcp/status")
def mcp_status_fragment():
    info = mcp_client.status()
    tools = info.get("tools") or []
    detail = ""
    if tools:
        chips = " ".join(f'<span class="chip">{escape(str(t))}</span>' for t in tools)
        detail = f"{len(tools)} tools registered: {chips}"
    return _status_line("MCP server", info, detail)


@ui_bp.get("/rag/status")
def rag_status_fragment():
    info = rag_client.status()
    index = info.get("index") or {}
    detail = ""
    if info.get("reachable"):
        detail = (
            f'{escape(str(index.get("chunks", 0)))} chunks from {escape(str(index.get("sources", 0)))} documents, '
            f'retrieval {escape(str(index.get("retrieval_mode", "unknown")))}, '
            f'model {escape(str(info.get("model", "unknown")))}.'
        )
    return _status_line("RAG server", info, detail)


@ui_bp.get("/mcp/tools")
def mcp_tools_fragment():
    try:
        tools = mcp_client.list_tools()
    except (
        mcp_client.MCPDisabled,
        mcp_client.MCPUnreachable,
        mcp_client.MCPProtocolError,
    ) as exc:
        return _integration_alert(exc)

    items = "".join(
        f"""
        <li>
          <div class="history-head">
            <span class="chip">{escape(t.name)}</span>
            <span class="muted">requires: {escape(", ".join(t.input_schema.get("required", [])) or "none")}</span>
          </div>
          <p>{escape(t.description.splitlines()[0] if t.description else "")}</p>
        </li>"""
        for t in tools
    )
    return f"""
    <p class="muted">{len(tools)} tools registered on the shared MCP server at
    <code>{escape(mcp_client.server_url())}</code> (via <code>tools/list</code>).</p>
    <ul class="insight-history">{items}</ul>"""


@ui_bp.post("/mcp/tool")
def mcp_tool_fragment():
    customer_id = _customer(request.form)
    month, year = _period(request.form)
    try:
        result = mcp_client.transactions_spending(customer_id, month, year)
    except (
        mcp_client.MCPDisabled,
        mcp_client.MCPUnreachable,
        mcp_client.MCPProtocolError,
    ) as exc:
        return _integration_alert(exc)

    if result.is_error:
        return _alert(f"The MCP tool returned an error: {result.text}", "warn")

    data = result.structured or {}
    totals = data.get("totals_by_category") or {}
    rows = "".join(
        f"""
        <tr>
          <td><span class="category">{escape(str(category))}</span></td>
          <td class="num">{_money(amount)}</td>
        </tr>"""
        for category, amount in totals.items()
    )

    return f"""
    <article class="insight-card">
      <h3>MCP tool result: <code>transactions_spending</code></h3>
      <p class="muted">Structured result returned by the shared MCP server for customer
      {customer_id}, {month:02d}/{year}. Arguments: <code>{escape(json.dumps(result.arguments))}</code></p>
      <div class="summary-strip">
        <div class="stat">
          <span class="stat-label">Total spent</span>
          <span class="stat-value">{_money(data.get('total_spent', 0))}</span>
          <span class="stat-sub">across {data.get('transaction_count', 0)} transactions</span>
        </div>
        <div class="stat">
          <span class="stat-label">Customer</span>
          <span class="stat-value">{customer_id}</span>
          <span class="stat-sub">month {month:02d}/{year}</span>
        </div>
      </div>
      <div class="table-scroll">
        <table class="budget-table">
          <thead><tr><th>Category</th><th>Spent</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      <p class="muted insight-meta">Source of record: <code>{escape(str(data.get('source', 'unknown')))}</code></p>
    </article>"""


CONFIDENCE_BADGE = {"High": "ok", "Medium": "near", "Low": "over"}
_CITATION_MARK = re.compile(r"\[([a-z0-9-]+#\d{3})\]")


def _confidence_badge(category):
    cls = CONFIDENCE_BADGE.get(category)
    if cls is None:
        return f'<span class="chip">Confidence: {escape(str(category))}</span>'
    return f'<span class="badge badge-{cls}">Confidence: {escape(str(category))}</span>'


def _answer_html(answer):
    safe = escape(str(answer))
    return _CITATION_MARK.sub(lambda m: f'<span class="chip">{m.group(1)}</span>', safe)


@ui_bp.post("/rag/query")
def rag_query_fragment():
    question = (request.form.get("query") or "").strip()
    if not question:
        return _alert("Type a question about the SmartBank project first.", "warn")
    if len(question) > rag_client.MAX_QUERY_CHARS:
        return _alert(
            f"Questions are limited to {rag_client.MAX_QUERY_CHARS} characters.", "warn"
        )

    try:
        answer = rag_client.query(question)
    except (rag_client.RAGDisabled, rag_client.RAGUnreachable) as exc:
        return _integration_alert(exc)
    except rag_client.RAGError as exc:
        retrieved = (exc.payload.get("retrieval_summary") or {}).get("retrieved_count")
        extra = (
            f" {retrieved} chunks were retrieved before the failure."
            if retrieved is not None
            else ""
        )
        message = str(exc).rstrip(".")
        return _alert(f"RAG server error (HTTP {exc.status}): {message}.{extra}")

    summary = answer.get("retrieval_summary") or {}
    meta = (
        f"k={summary.get('k')}, retrieved {summary.get('retrieved_count')}, "
        f"relevant {summary.get('relevant_count')}, mode {escape(str(summary.get('retrieval_mode')))}, "
        f"top chunk {escape(str(summary.get('top_chunk')))}"
    )
    model = (answer.get("generation") or {}).get("model") or "not called"

    if answer.get("insufficient_context"):
        return f"""
        <article class="insight-card rag-insufficient">
          <h3>Insufficient context</h3>
          <p class="alert alert-warn">{escape(str(answer.get('answer', '')))}</p>
          <p class="muted">No chunk passed the relevance threshold for
          <em>{escape(question)}</em>, so no answer was generated and no citations exist.
          {_confidence_badge(answer.get('confidence_category', 'Unknown'))}</p>
          <p class="muted insight-meta">Retrieval: {meta}. Model: {escape(str(model))}.</p>
        </article>"""

    citations = "".join(
        f"""
        <li>
          <div class="history-head">
            <span class="chip">{escape(str(c.get('chunk_id', '')))}</span>
            <span class="muted">{escape(str(c.get('title', '')))} &middot; tier {escape(str(c.get('authority_tier', '')))}</span>
          </div>
        </li>"""
        for c in answer.get("citations") or []
    )

    return f"""
    <article class="insight-card rag-answer">
      <h3>Grounded answer {_confidence_badge(answer.get('confidence_category'))}</h3>
      <p>{_answer_html(answer.get('answer', ''))}</p>
      <h4 class="muted">Citations ({len(answer.get('citations') or [])})</h4>
      <ul class="insight-history">{citations}</ul>
      <p class="muted insight-meta">Answer generated only from the cited chunks. Retrieval: {meta}.
      Model: {escape(str(model))}. Confidence is derived from the evidence, not the model.</p>
    </article>"""


# ---------------------------------------------------------------------------
# Multi-Agent UI fragments
# ---------------------------------------------------------------------------

_MA_ERRORS = (
    multi_agent_client.MultiAgentDisabled,
    multi_agent_client.MultiAgentUnreachable,
    multi_agent_client.MultiAgentError,
)
STAGE_BADGE = {
    "completed": "ok",
    "running": "near",
    "timed_out": "near",
    "failed": "over",
}
VERDICT_BADGE = {"accept": "ok", "revise": "near", "escalate": "over"}
DECISION_LABEL = {
    "accept": "Accept",
    "partially_accept": "Partially accept",
    "reject": "Reject",
}


def _ma_alert(exc):
    if isinstance(exc, multi_agent_client.MultiAgentError):
        return _alert(
            f"Multi-Agent Server (HTTP {exc.status}): {str(exc).rstrip('.')}.",
            "warn" if exc.status < 500 else "error",
        )
    return _alert(str(exc), "warn")


def _chips(items):
    return " ".join(f'<span class="chip">{escape(str(i))}</span>' for i in items)


def _stage_badges(stages):
    out = []
    for s in stages:
        cls = STAGE_BADGE.get(s.get("status"), "near")
        text = f"{s.get('role')} {s.get('status')}"
        if s.get("attempt", 1) > 1:
            text += f" #{s['attempt']}"
        if s.get("fallback"):
            text += " fallback"
        if s.get("duration_seconds") is not None:
            text += f" {s['duration_seconds']}s"
        out.append(f'<span class="badge badge-{cls}">{escape(text)}</span>')
    return " ".join(out)


def _list(items, cls="muted"):
    if not items:
        return ""
    return (
        "<ul>"
        + "".join(f'<li class="{cls}">{escape(str(i))}</li>' for i in items)
        + "</ul>"
    )


def _plan_html(plan):
    if not plan:
        return ""
    tasks = ""
    for t in plan.get("tasks") or []:
        if t.get("kind") == "api":
            tasks += (
                f'<li><span class="chip">{escape(str(t.get("id")))}</span> <code>GET {escape(str(t.get("endpoint")))}</code> '
                f'<span class="muted">{escape(json.dumps(t.get("params") or {}, sort_keys=True))}</span></li>'
            )
        else:
            tasks += (
                f'<li><span class="chip">{escape(str(t.get("id")))}</span> analysis after {escape(", ".join(t.get("depends_on") or []))}: '
                f'{escape(str(t.get("instruction", "")))}</li>'
            )
    meta = plan.get("meta") or {}
    return f"""
      <section class="ma-section">
        <h4>Plan <span class="muted">{escape(str(meta.get("source", "")))}, {escape(str(len(plan.get("tasks") or [])))} tasks</span></h4>
        <p>{escape(str(plan.get("objective", "")))}</p>
        <ul class="insight-history">{tasks}</ul>
        <p class="muted">Success criteria</p>{_list(plan.get("success_criteria") or [])}
        {('<p class="muted">Limitations</p>' + _list(plan.get("limitations"))) if plan.get("limitations") else ""}
      </section>"""


def _result_html(result):
    if not result:
        return ""
    rows = ""
    for e in result.get("evidence") or []:
        ok = e.get("status") == "ok"
        detail = (
            f"HTTP {e.get('http_status')} {e.get('duration_seconds')}s"
            if ok
            else str(e.get("error", ""))
        )
        rows += (
            f'<tr><td><span class="chip">{escape(str(e.get("task_id")))}</span></td>'
            f'<td><code>{escape(str(e.get("endpoint")))}</code></td>'
            f'<td><span class="badge badge-{"ok" if ok else "over"}">{escape(str(e.get("status")))}</span></td>'
            f'<td class="muted">{escape(detail)}</td></tr>'
        )
    findings = "".join(
        f'<li><span class="chip">{escape(str(f.get("task_id")))}</span> {escape(str(f.get("statement")))} '
        f'<span class="muted">evidence {escape(", ".join(f.get("evidence") or []))}</span></li>'
        for f in result.get("findings") or []
    )
    meta = result.get("meta") or {}
    unproven = result.get("request_only_numbers") or []
    return f"""
      <section class="ma-section">
        <h4>Evidence</h4>
        <div class="table-scroll"><table class="budget-table">
          <thead><tr><th>Task</th><th>Endpoint</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>{rows}</tbody></table></div>
        <h4>Findings <span class="muted">{escape(str(meta.get("source", "")))}, attempt {escape(str(meta.get("attempt", 1)))}</span></h4>
        <ul class="insight-history">{findings}</ul>
        <h4>Answer</h4>
        <p>{escape(str(result.get("answer") or ""))}</p>
        {('<p class="muted">Gaps</p>' + _list(result.get("gaps"))) if result.get("gaps") else ""}
        {('<p class="muted">Figures from the request, not the evidence: ' + _chips(unproven) + '</p>') if unproven else ""}
      </section>"""


def _review_html(review):
    if not review:
        return ""
    verdict = str(review.get("verdict", ""))
    cls = VERDICT_BADGE.get(verdict, "near")
    criteria = "".join(
        f'<li><span class="badge badge-{"ok" if c.get("met") is True else "over"}">{escape(str(c.get("index")))} '
        f'{"met" if c.get("met") is True else ("not met" if c.get("met") is False else "not evaluated")}</span> {escape(str(c.get("note", "")))}</li>'
        for c in review.get("criteria") or []
    )
    defects = "".join(
        f'<li><span class="badge badge-over">{escape(str(d.get("severity")))}</span> {escape(str(d.get("about", "")))}: {escape(str(d.get("note", "")))}</li>'
        for d in review.get("defects") or []
    )
    meta = review.get("meta") or {}
    escalated = ""
    if review.get("escalated"):
        escalated = f'<p class="alert alert-warn">Escalated: {escape(str(review.get("escalation_reason", "")))}</p>'
    return f"""
      <section class="ma-section">
        <h4>Review <span class="badge badge-{cls}">{escape(verdict)}</span> <span class="muted">{escape(str(meta.get("source", "")))}, attempt {escape(str(meta.get("attempt", 1)))}</span></h4>
        <p>{escape(str(review.get("summary") or ""))}</p>
        {escalated}
        <ul class="insight-history">{criteria}</ul>
        {('<p class="muted">Defects</p><ul class="insight-history">' + defects + '</ul>') if defects else ""}
        {('<p class="muted">Risks</p>' + _list(review.get("risks"))) if review.get("risks") else ""}
        {('<p class="muted">Revision notes</p>' + _list(review.get("revision_notes"))) if review.get("revision_notes") else ""}
      </section>"""


def _decision_form(workflow_id):
    workflow_id = escape(str(workflow_id))
    buttons = []
    for value, label in DECISION_LABEL.items():
        button_class = "btn btn-primary" if value == "accept" else "btn"
        buttons.append(
            '<button type="button" '
            f'hx-post="/ui/multi-agent/workflows/{workflow_id}/decision" '
            'hx-include="closest .decision-form" '
            f'hx-target="#ma-{workflow_id}" '
            'hx-swap="outerHTML" '
            f'hx-indicator="#ma-{workflow_id} .htmx-indicator" '
            'hx-disabled-elt="this" '
            f'hx-vals=\'{{"decision": "{value}"}}\' '
            f'class="{button_class}">{label}</button>'
        )
    buttons_html = "".join(buttons)
    return f"""
      <section class="ma-section">
        <h4>Decision</h4>
        <form class="decision-form">
          <input type="text" name="reviewer" maxlength="60" placeholder="Reviewer name">
          <textarea name="note" rows="2" maxlength="{multi_agent_client.MAX_NOTE_CHARS}" placeholder="Correction note (required for partially accept)"></textarea>
          <div class="form-actions">{buttons_html} <span class="htmx-indicator muted">Sending</span></div>
        </form>
      </section>"""


def _response_html(final):
    if not final:
        return ""
    if not final.get("released"):
        return f"""
      <section class="ma-section">
        <h4>Final response <span class="badge badge-over">withheld</span></h4>
        <p class="muted">Decision {escape(str(final.get("decision")))} by {escape(str(final.get("decided_by", "")))}.</p>
        {('<p>' + escape(str(final.get("correction_note"))) + '</p>') if final.get("correction_note") else ""}
      </section>"""
    return f"""
      <section class="ma-section ma-final">
        <h4>Final response <span class="badge badge-ok">released</span> <span class="muted">{escape(str(final.get("decision")))} by {escape(str(final.get("decided_by", "")))} at {escape(str(final.get("released_at", "")))}</span></h4>
        <p>{escape(str(final.get("answer") or ""))}</p>
        {('<p class="muted">Correction: ' + escape(str(final.get("correction_note"))) + '</p>') if final.get("correction_note") else ""}
        {('<p class="muted">Risks</p>' + _list(final.get("risks"))) if final.get("risks") else ""}
      </section>"""


def _retry_card(workflow_id, message=""):
    workflow_id = escape(str(workflow_id))
    return f"""
    <article class="insight-card ma-card" id="ma-{workflow_id}"
      hx-get="/ui/multi-agent/workflows/{workflow_id}" hx-trigger="every 2s" hx-swap="outerHTML">
      <div class="history-head">
        <span class="chip">{workflow_id}</span>
        <span class="badge badge-near">Retrying</span>
      </div>
      <p class="muted">The workflow is temporarily unavailable; the card is retrying automatically.</p>
      { _alert(message or "The server is still recovering.", "warn") }
    </article>"""


def _workflow_card(full, message=""):
    workflow_id = escape(str(full.get("workflow_id", "")))
    state = str(full.get("state", ""))
    running = state not in (
        multi_agent_client.STATE_AWAITING,
        *multi_agent_client.TERMINAL_STATES,
    )
    poll = (
        f' hx-get="/ui/multi-agent/workflows/{workflow_id}" hx-trigger="every 2s" hx-swap="outerHTML"'
        if running
        else ""
    )
    state_cls = {
        "awaiting_human_review": "near",
        "accepted": "ok",
        "partially_accepted": "ok",
        "rejected": "over",
        "failed": "over",
    }.get(state, "near")
    context = full.get("context") or {}
    head = (
        f'Customer {escape(str(context.get("customer_id", "")))}, '
        f'{escape(str(context.get("month", "")))}/{escape(str(context.get("year", "")))}'
    )
    error = (
        f'<p class="alert alert-error">{escape(str(full.get("error")))}</p>'
        if full.get("error")
        else ""
    )
    body = (
        _plan_html(full.get("plan"))
        + _result_html(full.get("result"))
        + _review_html(full.get("review"))
    )
    if state == multi_agent_client.STATE_AWAITING:
        body += _decision_form(workflow_id)
    body += _response_html(full.get("final_response"))
    revisions = (
        f' <span class="muted">revisions {escape(str(full.get("revisions")))}</span>'
        if full.get("revisions")
        else ""
    )
    return f"""
    <article class="insight-card ma-card" id="ma-{workflow_id}"{poll}>
      <div class="history-head">
        <span class="chip">{escape(str(workflow_id))}</span>
        <span class="badge badge-{state_cls}">{escape(state)}</span>{revisions}
        <span class="htmx-indicator muted">{"Running" if running else ""}</span>
      </div>
      <p class="muted">{head} &middot; {escape(str(full.get("request", "")))}</p>
      <p class="muted">{_stage_badges(full.get("stages") or [])}</p>
      {message}{error}{body}
    </article>"""


def _load_card(workflow_id, message=""):
    try:
        full = multi_agent_client.workflow(workflow_id)
    except _MA_ERRORS as exc:
        return _retry_card(workflow_id, str(exc))
    if not multi_agent_client.is_transactions(full):
        return _alert(f"Unknown transactions workflow {workflow_id}.", "warn")
    return _workflow_card(full, message)


def _operator_alert(*, state_changing):
    refused = operator_check(request.headers, state_changing=state_changing)
    if refused:
        return _alert(refused[0], "warn")
    return None


@ui_bp.get("/multi-agent/status")
def multi_agent_status_fragment():
    info = multi_agent_client.status()
    detail = ""
    if info.get("reachable"):
        pipeline = " &rarr; ".join(escape(str(p)) for p in info.get("pipeline") or [])
        detail = f'{pipeline} &middot; {escape(str(info.get("pending", 0)))} pending &middot; auth {escape(str(info.get("auth", "")))}'
    return _status_line("Multi-Agent server", info, detail)


@ui_bp.post("/multi-agent/workflows")
def multi_agent_start_fragment():
    if not (
        request.headers.get("HX-Request", "").lower() == "true"
        or request.headers.get("X-Requested-With")
    ):
        return _alert("Start workflows from the transactions panel.", "warn")
    text = (request.form.get("request") or "").strip()
    if not text:
        return _alert("Type the request first.", "warn")
    if len(text) > multi_agent_client.MAX_REQUEST_CHARS:
        return _alert(
            f"Requests are limited to {multi_agent_client.MAX_REQUEST_CHARS} characters.",
            "warn",
        )
    customer_id = _customer(request.form)
    month, year = _period(request.form)
    try:
        summary = multi_agent_client.start(text, customer_id, month, year)
    except _MA_ERRORS as exc:
        return _ma_alert(exc)
    return _load_card(summary["workflow_id"])


@ui_bp.get("/multi-agent/workflows/<workflow_id>")
def multi_agent_workflow_fragment(workflow_id):
    return _operator_alert(state_changing=False) or _load_card(workflow_id)


@ui_bp.post("/multi-agent/workflows/<workflow_id>/decision")
def multi_agent_decision_fragment(workflow_id):
    refused = _operator_alert(state_changing=True)
    if refused:
        return refused
    decision = (request.form.get("decision") or "").strip()
    note = (request.form.get("note") or "").strip()
    reviewer = (request.form.get("reviewer") or "").strip()[:60]
    try:
        summary = multi_agent_client.workflow_status(workflow_id)
        if not multi_agent_client.is_transactions(summary):
            return _alert(
                f"Unknown transactions workflow {escape(str(workflow_id))}.", "warn"
            )
        multi_agent_client.decide(workflow_id, decision, note, by=decided_by(reviewer))
    except multi_agent_client.MultiAgentError as exc:
        if exc.status in (400, 409):
            return _load_card(workflow_id, _alert(f"{str(exc).rstrip('.')}.", "warn"))
        return _ma_alert(exc)
    except _MA_ERRORS as exc:
        return _ma_alert(exc)
    return _load_card(workflow_id)
