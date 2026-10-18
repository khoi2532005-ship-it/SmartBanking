"""HTML fragment endpoints for the HTMX frontend.

The JSON API in budgets.py / insights.py is the contract other features
consume. These endpoints exist only to return HTML fragments that HTMX swaps
into the page, so the frontend needs no client-side rendering logic.
"""

import json
import re
from datetime import date
from html import escape

from flask import Blueprint, request

from services import database_api, insight_service, mcp_client, multi_agent_client, rag_client, transactions_client
from services.budget_logic import build_summary


ui_bp = Blueprint("ui", __name__, url_prefix="/ui")


def _current_period():
    today = date.today()
    return today.month, today.year


def _args_period(source):
    month, year = _current_period()
    try:
        return int(source.get("month") or month), int(source.get("year") or year)
    except (TypeError, ValueError):
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


# ---------------------------------------------------------------------------
# Budget list
# ---------------------------------------------------------------------------

def _budget_row(line):
    status_class = {
        "OVER_BUDGET": "over",
        "NEAR_LIMIT": "near",
        "ON_TRACK": "ok",
    }[line["status"]]

    status_label = {
        "OVER_BUDGET": "Over budget",
        "NEAR_LIMIT": "Near limit",
        "ON_TRACK": "On track",
    }[line["status"]]

    # The bar itself is capped at 100% width; the badge carries the overspend.
    bar_width = min(line["percent_used"], 100.0)

    if line["over_budget"]:
        remaining_cell = f'<span class="over-by">{_money(line["over_by"])} over</span>'
    else:
        remaining_cell = f'{_money(line["remaining"])} left'

    budget_id = line["budget_id"]
    category = escape(str(line["category"]))

    return f"""
    <tr class="budget-row is-{status_class}">
      <td>
        <span class="category">{category}</span>
        <span class="badge badge-{status_class}">{status_label}</span>
      </td>
      <td class="num">{_money(line["spent"])} <span class="muted">of {_money(line["monthly_limit"])}</span></td>
      <td class="bar-cell">
        <div class="progress" role="img"
             aria-label="{line['percent_used']} percent of budget used">
          <div class="progress-bar bar-{status_class}" style="width:{bar_width}%"></div>
        </div>
        <span class="pct">{line["percent_used"]}%</span>
      </td>
      <td class="num">{remaining_cell}</td>
      <td class="actions">
        <form class="inline-edit"
              hx-put="/ui/budgets/{budget_id}"
              hx-target="#budget-list"
              hx-swap="innerHTML">
          <input type="number" name="monthly_limit" step="0.01" min="0.01"
                 value="{line['monthly_limit']}" aria-label="New limit for {category}">
          <button type="submit" class="btn btn-small">Save</button>
        </form>
        <button type="button" class="btn btn-small btn-ai"
                hx-post="/ui/budgets/{budget_id}/explain"
                hx-target="#insight-panel"
                hx-swap="innerHTML"
                hx-indicator="#insight-spinner">Explain</button>
        <button type="button" class="btn btn-small btn-danger"
                hx-delete="/ui/budgets/{budget_id}"
                hx-target="#budget-list"
                hx-swap="innerHTML"
                hx-confirm="Delete the {category} budget?">Delete</button>
      </td>
    </tr>"""


def _render_budget_list(customer_id, month, year, notice=""):
    budgets = database_api.search_budgets(
        {"customer_id": customer_id, "month": month, "year": year}
    )
    spend_totals, source, _ = transactions_client.spend_by_category(
        customer_id, month, year
    )
    summary = build_summary(budgets, spend_totals)
    totals = summary["totals"]

    if not budgets:
        return (
            notice
            + '<p class="empty">No budgets for this period yet. '
            "Create one using the form above.</p>"
        )

    source_label = (
        "live Transactions API"
        if source == "transactions-api"
        else "mock transaction data (Transactions API unavailable)"
    )

    rows = "".join(_budget_row(line) for line in summary["budgets"])

    over_count = totals["over_budget_count"]
    headline_class = "over" if over_count else "ok"
    headline = (
        f"{over_count} of {totals['budget_count']} categories over budget"
        if over_count
        else f"All {totals['budget_count']} categories within budget"
    )

    unbudgeted = ""
    if summary["unbudgeted_spending"]:
        items = ", ".join(
            f"{escape(u['category'])} {_money(u['spent'])}"
            for u in summary["unbudgeted_spending"]
        )
        unbudgeted = (
            f'<p class="muted unbudgeted">Spending with no budget set: {items}</p>'
        )

    return f"""{notice}
    <div class="summary-strip">
      <div class="stat">
        <span class="stat-label">Total spent</span>
        <span class="stat-value">{_money(totals['total_spent'])}</span>
        <span class="stat-sub">of {_money(totals['total_limit'])} budgeted</span>
      </div>
      <div class="stat">
        <span class="stat-label">Remaining</span>
        <span class="stat-value">{_money(totals['total_remaining'])}</span>
        <span class="stat-sub">{totals['percent_used']}% of budget used</span>
      </div>
      <div class="stat stat-{headline_class}">
        <span class="stat-label">Status</span>
        <span class="stat-value">{headline}</span>
        <span class="stat-sub">Period {month:02d}/{year}</span>
      </div>
    </div>
    <table class="budget-table">
      <thead>
        <tr><th>Category</th><th>Spent</th><th>Progress</th><th>Remaining</th><th>Actions</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    {unbudgeted}
    <p class="muted source-note">Actual spending read over HTTP from the
    {source_label}.</p>"""


@ui_bp.get("/categories-options")
def category_options():
    """<option> list for the create-budget form."""
    try:
        categories = database_api.search_categories()
    except Exception as exc:
        return f'<option value="">Could not load categories ({escape(str(exc))})</option>'

    options = "".join(
        f'<option value="{escape(row["name"])}">{escape(row["name"])}</option>'
        for row in categories
    )
    return '<option value="">Choose a category...</option>' + options


@ui_bp.get("/budgets")
def budget_list():
    customer_id = _customer(request.args)
    month, year = _args_period(request.args)
    try:
        return _render_budget_list(customer_id, month, year)
    except Exception as exc:
        return _alert(f"Could not load budgets: {exc}")


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------

@ui_bp.post("/budgets")
def create_budget():
    form = request.form
    customer_id = _customer(form)
    month, year = _args_period(form)

    category = (form.get("category") or "").strip()
    if not category:
        return _alert("Choose a category.")

    try:
        monthly_limit = float(form.get("monthly_limit") or 0)
    except ValueError:
        return _alert("Monthly limit must be a number.")

    if monthly_limit <= 0:
        return _alert("Monthly limit must be greater than zero.")

    try:
        response = database_api.create_budget(
            {
                "customer_id": customer_id,
                "category": category,
                "monthly_limit": round(monthly_limit, 2),
                "month": month,
                "year": year,
            }
        )
        if response.status_code == 409:
            notice = _alert(
                f"A {category} budget already exists for {month:02d}/{year}. "
                "Edit its limit instead.",
                "warn",
            )
        elif response.status_code >= 400:
            notice = _alert(response.json().get("error", "Could not create budget."))
        else:
            notice = _alert(
                f"{category} budget created with a {_money(monthly_limit)} limit.",
                "success",
            )
        return _render_budget_list(customer_id, month, year, notice)
    except Exception as exc:
        return _alert(f"Could not create budget: {exc}")


@ui_bp.put("/budgets/<int:budget_id>")
def update_budget(budget_id):
    form = request.form
    try:
        monthly_limit = float(form.get("monthly_limit") or 0)
    except ValueError:
        return _alert("Monthly limit must be a number.")

    if monthly_limit <= 0:
        return _alert("Monthly limit must be greater than zero.")

    try:
        budget = database_api.get_budget(budget_id)
        response = database_api.update_budget(
            budget_id, {"monthly_limit": round(monthly_limit, 2)}
        )
        if response.status_code >= 400:
            notice = _alert(response.json().get("error", "Could not update budget."))
        else:
            notice = _alert(
                f"{budget['category']} limit updated to {_money(monthly_limit)}.",
                "success",
            )
        return _render_budget_list(
            budget["customer_id"], budget["month"], budget["year"], notice
        )
    except Exception as exc:
        return _alert(f"Could not update budget: {exc}")


@ui_bp.delete("/budgets/<int:budget_id>")
def delete_budget(budget_id):
    try:
        budget = database_api.get_budget(budget_id)
        response = database_api.delete_budget(budget_id)
        if response.status_code >= 400:
            notice = _alert(response.json().get("error", "Could not delete budget."))
        else:
            notice = _alert(f"{budget['category']} budget deleted.", "success")
        return _render_budget_list(
            budget["customer_id"], budget["month"], budget["year"], notice
        )
    except Exception as exc:
        return _alert(f"Could not delete budget: {exc}")


# ---------------------------------------------------------------------------
# AI insight panel
# ---------------------------------------------------------------------------

def _insight_card(title, body, model_used, source, extra=""):
    source_note = (
        "live Transactions API"
        if source == "transactions-api"
        else "mock transaction data"
    )
    paragraphs = "".join(
        f"<p>{escape(chunk.strip())}</p>"
        for chunk in str(body).split("\n")
        if chunk.strip()
    )
    return f"""
    <article class="insight-card">
      <h3>{escape(title)}</h3>
      {paragraphs}
      {extra}
      <p class="muted insight-meta">Generated by Ollama running
      <code>{escape(str(model_used))}</code>, using {source_note}.</p>
    </article>"""


@ui_bp.post("/insight")
def monthly_insight():
    customer_id = _customer(request.form)
    month, year = _args_period(request.form)

    response, status = insight_service.monthly_insight(customer_id, month, year)
    if status >= 400:
        return _alert(response.get("error", "AI request failed."))

    over = response.get("over_budget_categories") or []
    extra = ""
    if over:
        chips = "".join(
            f'<span class="chip chip-over">{escape(c)}</span>' for c in over
        )
        extra = f'<div class="chips">Over budget: {chips}</div>'

    return _insight_card(
        f"Spending insight for {month:02d}/{year}",
        response.get("insight", ""),
        response.get("model_used"),
        response.get("spending_source"),
        extra,
    )


@ui_bp.post("/budgets/<int:budget_id>/explain")
def explain_budget(budget_id):
    response, status = insight_service.explain_budget(budget_id)
    if status >= 400:
        return _alert(response.get("error", "AI request failed."))

    status_words = str(response.get("status", "")).replace("_", " ").lower()
    return _insight_card(
        f"Why {response.get('category')} is {status_words}",
        response.get("insight", ""),
        response.get("model_used"),
        response.get("spending_source"),
    )


@ui_bp.get("/insights")
def insight_history():
    customer_id = _customer(request.args)
    try:
        insights = database_api.search_insights(
            {"customer_id": customer_id, "limit": 10}
        )
    except Exception as exc:
        return _alert(f"Could not load insight history: {exc}")

    if not insights:
        return '<p class="empty">No insights generated yet.</p>'

    items = "".join(
        f"""
        <li>
          <div class="history-head">
            <span class="chip">{escape(str(row.get('category', '-')))}</span>
            <span class="muted">{escape(str(row.get('generated_at', ''))[:16])}</span>
            <code class="muted">{escape(str(row.get('model_used', '')))}</code>
          </div>
          <p>{escape(str(row.get('insight_text', '')))}</p>
        </li>"""
        for row in insights
    )
    return f'<ul class="insight-history">{items}</ul>'


# ---------------------------------------------------------------------------
# Release 1: shared MCP server (HTMX fragments)
# ---------------------------------------------------------------------------

STATUS_BADGE = {"OVER_BUDGET": ("over", "Over budget"),
                "NEAR_LIMIT": ("near", "Near limit"),
                "ON_TRACK": ("ok", "On track")}


def _integration_alert(exc):
    """The same readable failure for every fragment: disabled, down, or broken."""
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled)):
        return _alert(str(exc), "warn")
    return _alert(str(exc))


def _status_line(label, info, detail=""):
    """Badge, address and counts for a shared server. Always HTTP 200."""
    url = f'<code>{escape(str(info.get("url", "")))}</code>'
    if not info.get("enabled"):
        flag = {"MCP": "MCP_ENABLED=false", "RAG": "RAG_ENABLED=false"}.get(label.split()[0], "MULTI_AGENT_ENABLED=false")
        return f'<span class="badge badge-near">Inactive</span> <code>{flag}</code>'
    if info.get("reachable"):
        return f'<span class="badge badge-ok">Reachable</span> {url}' + (f" &middot; {detail}" if detail else "")
    return (f'<span class="badge badge-over">Unreachable</span> {url} &middot; '
            f'{escape(str(info.get("error", "no response")))}')


@ui_bp.get("/mcp/status")
def mcp_status_fragment():
    info = mcp_client.status()
    tools = info.get("tools") or []
    detail = ""
    if tools:
        chips = " ".join(f'<span class="chip">{escape(str(t))}</span>' for t in tools)
        detail = f"{len(tools)} tools: {chips}"
    return _status_line("MCP server", info, detail)


@ui_bp.get("/rag/status")
def rag_status_fragment():
    info = rag_client.status()
    index = info.get("index") or {}
    detail = ""
    if info.get("reachable"):
        detail = (f'{escape(str(index.get("chunks", 0)))} chunks &middot; '
                  f'{escape(str(index.get("sources", 0)))} documents &middot; '
                  f'{escape(str(index.get("retrieval_mode", "unknown")))} &middot; '
                  f'{escape(str(info.get("model", "unknown")))}')
    return _status_line("RAG server", info, detail)


@ui_bp.get("/mcp/tools")
def mcp_tools_fragment():
    """tools/list through this backend: what the shared server offers."""
    try:
        tools = mcp_client.list_tools()
    except (mcp_client.MCPDisabled, mcp_client.MCPUnreachable, mcp_client.MCPProtocolError) as exc:
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
    <ul class="insight-history">{items}</ul>"""


@ui_bp.post("/mcp/tool")
def mcp_tool_fragment():
    """Invoke this feature's tool on the shared MCP server and render the structured result."""
    customer_id = _customer(request.form)
    month, year = _args_period(request.form)

    try:
        result = mcp_client.budgeting_summary(customer_id, month, year)
    except (mcp_client.MCPDisabled, mcp_client.MCPUnreachable, mcp_client.MCPProtocolError) as exc:
        return _integration_alert(exc)

    if result.is_error:
        return _alert(f"The MCP tool returned an error: {result.text}", "warn")

    data = result.structured or {}
    totals = data.get("totals") or {}

    rows = ""
    for line in data.get("budgets") or []:
        cls, label = STATUS_BADGE.get(line.get("status"), ("ok", str(line.get("status", ""))))
        rows += f"""
        <tr>
          <td><span class="category">{escape(str(line.get("category", "")))}</span></td>
          <td class="num">{_money(line.get("spent", 0))} <span class="muted">of {_money(line.get("monthly_limit", 0))}</span></td>
          <td class="num">{line.get("percent_used", 0)}%</td>
          <td><span class="badge badge-{cls}">{label}</span></td>
        </tr>"""

    over = data.get("over_budget_categories") or []
    over_text = ", ".join(escape(str(c)) for c in over) if over else "none"

    return f"""
    <article class="insight-card">
      <h3>MCP tool result: <code>budgeting_summary</code></h3>
      <p class="muted">Customer {customer_id}, {month:02d}/{year} &middot; <code>{escape(json.dumps(result.arguments))}</code></p>
      <div class="summary-strip">
        <div class="stat">
          <span class="stat-label">Total spent</span>
          <span class="stat-value">{_money(totals.get("total_spent", 0))}</span>
          <span class="stat-sub">of {_money(totals.get("total_limit", 0))} budgeted</span>
        </div>
        <div class="stat">
          <span class="stat-label">Budgets</span>
          <span class="stat-value">{data.get("budget_count", 0)}</span>
          <span class="stat-sub">{totals.get("over_budget_count", 0)} over budget</span>
        </div>
        <div class="stat">
          <span class="stat-label">Over budget</span>
          <span class="stat-value">{over_text}</span>
          <span class="stat-sub">spending source: {escape(str(data.get("spending_source", "unknown")))}</span>
        </div>
      </div>
      <div class="table-scroll">
        <table class="budget-table">
          <thead><tr><th>Category</th><th>Spent</th><th>Used</th><th>Status</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </article>"""


# ---------------------------------------------------------------------------
# Release 1: shared RAG server (HTMX fragments)
# ---------------------------------------------------------------------------

CONFIDENCE_BADGE = {"High": "ok", "Medium": "near", "Low": "over"}
_CITATION_MARK = re.compile(r"\[([a-z0-9-]+#\d{3})\]")


def _confidence_badge(category):
    cls = CONFIDENCE_BADGE.get(category)
    if cls is None:
        return f'<span class="chip">Confidence: {escape(str(category))}</span>'
    return f'<span class="badge badge-{cls}">Confidence: {escape(str(category))}</span>'


def _answer_html(answer):
    """Escape the prose, then turn [chunk#001] markers into chips."""
    safe = escape(str(answer))
    return _CITATION_MARK.sub(lambda m: f'<span class="chip">{m.group(1)}</span>', safe)


@ui_bp.post("/rag/query")
def rag_query_fragment():
    question = (request.form.get("query") or "").strip()
    if not question:
        return _alert("Type a question about the SmartBank project first.", "warn")
    if len(question) > rag_client.MAX_QUERY_CHARS:
        return _alert(f"Questions are limited to {rag_client.MAX_QUERY_CHARS} characters.", "warn")

    try:
        answer = rag_client.query(question)
    except (rag_client.RAGDisabled, rag_client.RAGUnreachable) as exc:
        return _integration_alert(exc)
    except rag_client.RAGError as exc:
        retrieved = (exc.payload.get("retrieval_summary") or {}).get("retrieved_count")
        extra = f" {retrieved} chunks were retrieved before the failure." if retrieved is not None else ""
        message = str(exc).rstrip(".")          # server messages may already end with one
        return _alert(f"RAG server error (HTTP {exc.status}): {message}.{extra}")

    summary = answer.get("retrieval_summary") or {}
    meta = (
        f"k={summary.get('k')}, retrieved {summary.get('retrieved_count')}, "
        f"relevant {summary.get('relevant_count')}, mode {escape(str(summary.get('retrieval_mode')))}, "
        f"top chunk {escape(str(summary.get('top_chunk')))}"
    )
    model = (answer.get("generation") or {}).get("model") or "not called"

    # Distinct state: nothing in the approved documents supports an answer.
    if answer.get("insufficient_context"):
        return f"""
        <article class="insight-card rag-insufficient">
          <h3>Insufficient context</h3>
          <p class="alert alert-warn">{escape(str(answer.get("answer", "")))}</p>
          <p class="muted">{_confidence_badge(answer.get("confidence_category", "Unknown"))}</p>
          <p class="muted insight-meta">Retrieval: {meta}. Model: {escape(str(model))}.</p>
        </article>"""

    citations = "".join(
        f"""
        <li>
          <div class="history-head">
            <span class="chip">{escape(str(c.get("chunk_id", "")))}</span>
            <span class="muted">{escape(str(c.get("title", "")))} &middot; tier {escape(str(c.get("authority_tier", "")))}</span>
          </div>
        </li>"""
        for c in answer.get("citations") or []
    )
    return f"""
    <article class="insight-card rag-answer">
      <h3>Grounded answer {_confidence_badge(answer.get("confidence_category"))}</h3>
      <p>{_answer_html(answer.get("answer", ""))}</p>
      <h4 class="muted">Citations ({len(answer.get("citations") or [])})</h4>
      <ul class="insight-history">{citations}</ul>
      <p class="muted insight-meta">Retrieval: {meta}. Model: {escape(str(model))}.</p>
    </article>"""



# ---------------------------------------------------------------------------
# Release 2: shared Multi-Agent Server (HTMX fragments)
# ---------------------------------------------------------------------------

_MA_ERRORS = (multi_agent_client.MultiAgentDisabled, multi_agent_client.MultiAgentUnreachable,
              multi_agent_client.MultiAgentError)
STAGE_BADGE = {"completed": "ok", "running": "near", "timed_out": "near", "failed": "over"}
VERDICT_BADGE = {"accept": "ok", "revise": "near", "escalate": "over"}
DECISION_LABEL = {"accept": "Accept", "partially_accept": "Partially accept", "reject": "Reject"}


def _ma_alert(exc):
    if isinstance(exc, multi_agent_client.MultiAgentError):
        return _alert(f"Multi-Agent Server (HTTP {exc.status}): {str(exc).rstrip('.')}.", "warn" if exc.status < 500 else "error")
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
    return "<ul>" + "".join(f'<li class="{cls}">{escape(str(i))}</li>' for i in items) + "</ul>"


def _plan_html(plan):
    if not plan:
        return ""
    tasks = ""
    for t in plan.get("tasks") or []:
        if t.get("kind") == "api":
            tasks += (f'<li><span class="chip">{escape(str(t.get("id")))}</span> <code>GET {escape(str(t.get("endpoint")))}</code> '
                      f'<span class="muted">{escape(json.dumps(t.get("params") or {}, sort_keys=True))}</span></li>')
        else:
            tasks += (f'<li><span class="chip">{escape(str(t.get("id")))}</span> analysis after {escape(", ".join(t.get("depends_on") or []))}: '
                      f'{escape(str(t.get("instruction", "")))}</li>')
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
        detail = f"HTTP {e.get('http_status')} {e.get('duration_seconds')}s" if ok else str(e.get("error", ""))
        rows += (f'<tr><td><span class="chip">{escape(str(e.get("task_id")))}</span></td>'
                 f'<td><code>{escape(str(e.get("endpoint")))}</code></td>'
                 f'<td><span class="badge badge-{"ok" if ok else "over"}">{escape(str(e.get("status")))}</span></td>'
                 f'<td class="muted">{escape(detail)}</td></tr>')
    findings = "".join(
        f'<li><span class="chip">{escape(str(f.get("task_id")))}</span> {escape(str(f.get("statement")))} '
        f'<span class="muted">evidence {escape(", ".join(f.get("evidence") or []))}</span></li>'
        for f in result.get("findings") or [])
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
        for c in review.get("criteria") or [])
    defects = "".join(
        f'<li><span class="badge badge-over">{escape(str(d.get("severity")))}</span> {escape(str(d.get("about", "")))}: {escape(str(d.get("note", "")))}</li>'
        for d in review.get("defects") or [])
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
    buttons = "".join(
        f'<button type="submit" name="decision" value="{value}" class="btn{" btn-primary" if value == "accept" else ""}">{label}</button>'
        for value, label in DECISION_LABEL.items())
    return f"""
      <section class="ma-section">
        <h4>Decision</h4>
        <form class="decision-form" hx-post="/ui/multi-agent/workflows/{workflow_id}/decision"
              hx-target="#ma-{workflow_id}" hx-swap="outerHTML" hx-indicator="#ma-{workflow_id} .htmx-indicator">
          <textarea name="note" rows="2" maxlength="{multi_agent_client.MAX_NOTE_CHARS}" placeholder="Correction note (required for partially accept)"></textarea>
          <div class="form-actions">{buttons} <span class="htmx-indicator muted">Sending</span></div>
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


def _workflow_card(full, message=""):
    """The whole workflow as one swappable card; it polls itself while the stages run."""
    workflow_id = full.get("workflow_id", "")
    state = str(full.get("state", ""))
    running = state not in (multi_agent_client.STATE_AWAITING, *multi_agent_client.TERMINAL_STATES)
    poll = (f' hx-get="/ui/multi-agent/workflows/{workflow_id}" hx-trigger="every 2s" hx-swap="outerHTML"'
            if running else "")
    state_cls = {"awaiting_human_review": "near", "accepted": "ok", "partially_accepted": "ok", "rejected": "over", "failed": "over"}.get(state, "near")
    context = full.get("context") or {}
    head = (f'Customer {escape(str(context.get("customer_id", "")))}, '
            f'{escape(str(context.get("month", "")))}/{escape(str(context.get("year", "")))}')
    error = f'<p class="alert alert-error">{escape(str(full.get("error")))}</p>' if full.get("error") else ""
    body = _plan_html(full.get("plan")) + _result_html(full.get("result")) + _review_html(full.get("review"))
    if state == multi_agent_client.STATE_AWAITING:
        body += _decision_form(workflow_id)
    body += _response_html(full.get("final_response"))
    revisions = f' <span class="muted">revisions {escape(str(full.get("revisions")))}</span>' if full.get("revisions") else ""
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
        return _ma_alert(exc)
    return _workflow_card(full, message)


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
    text = (request.form.get("request") or "").strip()
    if not text:
        return _alert("Type the request first.", "warn")
    if len(text) > multi_agent_client.MAX_REQUEST_CHARS:
        return _alert(f"Requests are limited to {multi_agent_client.MAX_REQUEST_CHARS} characters.", "warn")
    customer_id = _customer(request.form)
    month, year = _args_period(request.form)
    try:
        summary = multi_agent_client.start(text, customer_id, month, year)
    except _MA_ERRORS as exc:
        return _ma_alert(exc)
    return _load_card(summary["workflow_id"])


@ui_bp.get("/multi-agent/workflows/<workflow_id>")
def multi_agent_workflow_fragment(workflow_id):
    return _load_card(workflow_id)


@ui_bp.post("/multi-agent/workflows/<workflow_id>/decision")
def multi_agent_decision_fragment(workflow_id):
    decision = (request.form.get("decision") or "").strip()
    note = (request.form.get("note") or "").strip()
    try:
        multi_agent_client.decide(workflow_id, decision, note)
    except multi_agent_client.MultiAgentError as exc:
        if exc.status in (400, 409):
            return _load_card(workflow_id, _alert(f"{str(exc).rstrip('.')}.", "warn"))
        return _ma_alert(exc)
    except _MA_ERRORS as exc:
        return _ma_alert(exc)
    return _load_card(workflow_id)
