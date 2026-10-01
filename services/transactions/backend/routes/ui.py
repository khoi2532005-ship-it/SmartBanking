"""HTML fragment endpoints for the Transactions UI."""

import json
import re
from datetime import date
from html import escape

from flask import Blueprint, request

from services import mcp_client, rag_client

ui_bp = Blueprint("ui", __name__, url_prefix="/ui")


def _current_period():
    today = date.today()
    return today.month, today.year


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
    if isinstance(exc, (mcp_client.MCPDisabled, rag_client.RAGDisabled)):
        return _alert(f"{exc} - this control is retained but inactive here.", "warn")
    return _alert(str(exc))


def _status_line(label, info, detail=""):
    url = f'<code>{escape(str(info.get("url", "")))}</code>'
    if not info.get("enabled"):
        return (f'<span class="badge badge-near">Inactive</span> {label} integration is '
                f'{escape(str(info.get("note", "disabled")))}: the controls below are retained '
                f'but make no network call.')
    if info.get("reachable"):
        return f'<span class="badge badge-ok">Reachable</span> {label} at {url}. {detail}'
    return (f'<span class="badge badge-over">Unreachable</span> {label} at {url}: '
            f'{escape(str(info.get("error", "no response")))}')


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
    customer_id = _customer(request.form)
    month, year = _current_period()
    try:
        result = mcp_client.transactions_spending(customer_id, month, year)
    except (mcp_client.MCPDisabled, mcp_client.MCPUnreachable, mcp_client.MCPProtocolError) as exc:
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
        return _alert(f"Questions are limited to {rag_client.MAX_QUERY_CHARS} characters.", "warn")

    try:
        answer = rag_client.query(question)
    except (rag_client.RAGDisabled, rag_client.RAGUnreachable) as exc:
        return _integration_alert(exc)
    except rag_client.RAGError as exc:
        retrieved = (exc.payload.get("retrieval_summary") or {}).get("retrieved_count")
        extra = f" {retrieved} chunks were retrieved before the failure." if retrieved is not None else ""
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
