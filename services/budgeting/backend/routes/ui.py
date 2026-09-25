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

from services import database_api, insight_service, mcp_client, rag_client, transactions_client
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
        return _alert(f"{exc} - this control is retained but inactive here.", "warn")
    return _alert(str(exc))


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
    <p class="muted">{len(tools)} tools registered on the shared MCP server at
    <code>{escape(mcp_client.server_url())}</code> (via <code>tools/list</code>).</p>
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
    source = data.get("source") or {}
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
      <p class="muted">Structured result returned by the shared MCP server for customer
      {customer_id}, {month:02d}/{year}. Arguments: <code>{escape(json.dumps(result.arguments))}</code></p>
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
      <p class="muted insight-meta">Tool boundary: read-only, one customer, one month.
      Source of record: <code>{escape(str(source.get("feature", "")))}</code>
      <code>{escape(str(source.get("endpoint", "")))}</code> at
      <code>{escape(str(source.get("service_url", "")))}</code>, via MCP server
      <code>{escape(mcp_client.server_url())}</code>.</p>
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

    try:
        answer = rag_client.query(question)
    except (rag_client.RAGDisabled, rag_client.RAGUnreachable) as exc:
        return _integration_alert(exc)
    except rag_client.RAGError as exc:
        retrieved = (exc.payload.get("retrieval_summary") or {}).get("retrieved_count")
        extra = f" {retrieved} chunks were retrieved before the failure." if retrieved is not None else ""
        return _alert(f"RAG server error (HTTP {exc.status}): {exc}.{extra}")

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
          <p class="muted">No chunk passed the relevance threshold for
          <em>{escape(question)}</em>, so no answer was generated and no citations exist.
          {_confidence_badge(answer.get("confidence_category", "Unknown"))}</p>
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
      <p class="muted insight-meta">Answer generated only from the cited chunks. Retrieval: {meta}.
      Model: {escape(str(model))}. Confidence is derived from the evidence, not the model.</p>
    </article>"""

