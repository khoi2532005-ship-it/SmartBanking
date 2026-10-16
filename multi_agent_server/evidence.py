"""Evidence collection: the Worker's api tasks, executed over the feature APIs.

Each api task in the plan becomes one evidence record: what was called, with
which parameters, whether it answered, how long it took, and a bounded summary
of the response. The summaries follow the Release 1 MCP tools (counts, totals,
statuses - never raw rows, balances or account numbers), so the model roles
and the UI see the same shape of evidence the MCP tools publish.
"""

from __future__ import annotations

import calendar
from collections import Counter
from typing import Any, Callable

from multi_agent_server import catalogue, config
from multi_agent_server.http import UpstreamError, build_url, fetch
from multi_agent_server.models import now_iso

MAX_LIST_ITEMS = 25
MAX_TEXT_CHARS = 200


def collect(plan: dict[str, Any], feature: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    """One evidence record per api task, in plan order."""
    return [collect_task(task, feature) for task in plan["tasks"] if task["kind"] == "api"]


def collect_task(task: dict[str, Any], feature: str) -> dict[str, Any]:
    entry = catalogue.endpoint(feature, task["endpoint"]) or {}
    params = request_params(task["params"], entry)
    base_url = config.SERVICE_URLS[feature]
    record: dict[str, Any] = {
        "task_id": task["id"],
        "kind": "api",
        "feature": feature,
        "endpoint": task["endpoint"],
        "url": build_url(base_url, task["endpoint"]),
        "params": params,
        "status": "ok",
        "http_status": None,
        "duration_seconds": None,
        "summary": {},
        "error": "",
        "collected_at": now_iso(),
    }
    try:
        result = fetch(base_url, task["endpoint"], params)
    except UpstreamError as exc:
        record["status"] = "error"
        record["error"] = f"{feature} service unavailable: {exc}"
        return record
    record["http_status"] = result.status_code
    record["duration_seconds"] = result.duration_seconds
    record["summary"] = summarise(task["endpoint"], result.payload, task["params"])
    return record


def request_params(params: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """The query the API receives. A period becomes a date range where the
    endpoint filters by date (the Transactions API), as the MCP tool does."""
    if not entry.get("translate_period"):
        return dict(params)
    clean = {k: v for k, v in params.items() if k not in ("month", "year")}
    if "month" in params and "year" in params:
        clean["date_from"], clean["date_to"] = period_bounds(int(params["month"]), int(params["year"]))
    return clean


def period_bounds(month: int, year: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"


# ---------------------------------------------------------------- summaries

def summarise(path: str, payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    summariser = SUMMARISERS.get(path, _generic)
    try:
        return summariser(payload, params)
    except (AttributeError, TypeError, ValueError, KeyError):
        return _generic(payload, params)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("items", "results", "data"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _budget_summary(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    lines = payload.get("budgets") or []
    return {
        "customer_id": payload.get("customer_id", params.get("customer_id")),
        "month": payload.get("month", params.get("month")),
        "year": payload.get("year", params.get("year")),
        "budget_count": len(lines),
        "totals": payload.get("totals") or {},
        "budgets": [
            {key: line.get(key) for key in
             ("category", "monthly_limit", "spent", "remaining", "percent_used", "status", "over_by")}
            for line in lines[:MAX_LIST_ITEMS]
        ],
        "over_budget_count": len(payload.get("over_budget_categories") or []),
        "over_budget_categories": payload.get("over_budget_categories") or [],
        "unbudgeted_spending": (payload.get("unbudgeted_spending") or [])[:MAX_LIST_ITEMS],
        "spending_source": payload.get("spending_source", "unknown"),
    }


def _spending(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    totals = payload.get("totals_by_category") or {}
    return {
        "customer_id": payload.get("customer_id", params.get("customer_id")),
        "month": payload.get("month", params.get("month")),
        "year": payload.get("year", params.get("year")),
        "spending_source": payload.get("spending_source", "unknown"),
        "totals_by_category": dict(sorted(totals.items())),
        "category_count": len(totals),
        "total_spent": round(sum(_number(v) for v in totals.values()), 2),
        "transaction_count": payload.get("transaction_count"),
    }


def _budgets(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "budget_count": len(rows),
        "budgets": [{key: row.get(key) for key in ("budget_id", "category", "monthly_limit", "month", "year")}
                    for row in rows[:MAX_LIST_ITEMS]],
    }


def _insights(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "insight_count": len(rows),
        "insights": [
            {"insight_id": row.get("insight_id"), "budget_id": row.get("budget_id"),
             "generated_at": row.get("generated_at"), "model_used": row.get("model_used"),
             "insight_text": str(row.get("insight_text") or "")[:MAX_TEXT_CHARS]}
            for row in rows[:5]
        ],
    }


def _categories(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    names = [row.get("name") for row in _rows(payload)] if _rows(payload) else \
        [str(item) for item in payload if isinstance(item, str)] if isinstance(payload, list) else []
    return {"category_count": len(names), "categories": names[:MAX_LIST_ITEMS]}


def _accounts(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    # Counts only: balances and account numbers stay behind the API boundary.
    return {
        "customer_id": params.get("customer_id"),
        "account_count": len(rows),
        "by_status": dict(Counter(str(r.get("status", "UNKNOWN")).upper() for r in rows)),
        "by_type": dict(Counter(str(r.get("account_type", "UNKNOWN")).upper() for r in rows)),
    }


def _loans(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "customer_id": params.get("customer_id"),
        "loan_count": len(rows),
        "by_status": dict(Counter(str(r.get("status", "UNKNOWN")).upper() for r in rows)),
        "loans": [{key: row.get(key) for key in ("loan_id", "loan_type", "requested_amount", "status")}
                  for row in rows[:MAX_LIST_ITEMS]],
    }


def _alerts(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "customer_id": params.get("customer_id"),
        "alert_count": len(rows),
        "by_severity": dict(Counter(str(r.get("severity", "unknown")).lower() for r in rows)),
        "by_status": dict(Counter(str(r.get("status", "unknown")).lower() for r in rows)),
    }


def _rules(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(payload)
    return {
        "rule_count": len(rows),
        "enabled_count": sum(1 for r in rows if r.get("enabled") in (1, True, "1", "true")),
        "rules": [{key: row.get(key) for key in ("rule_id", "rule_name", "rule_type", "severity", "enabled")}
                  for row in rows[:MAX_LIST_ITEMS]],
    }


def _transactions(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Totals of money leaving the account per category; the sign rule and the
    date range are the MCP transactions tool's."""
    rows = _rows(payload)
    totals: dict[str, float] = {}
    counted = 0
    for row in rows:
        amount = _number(row.get("amount"))
        if amount >= 0:
            continue
        category = row.get("category") or "Uncategorised"
        totals[category] = round(totals.get(category, 0.0) - amount, 2)
        counted += 1
    summary: dict[str, Any] = {
        "customer_id": params.get("customer_id"),
        "transaction_count": len(rows),
        "spending_count": counted,
        "total_spent": round(sum(totals.values()), 2),
        "totals_by_category": dict(sorted(totals.items())),
    }
    if "month" in params and "year" in params:
        summary["date_from"], summary["date_to"] = period_bounds(int(params["month"]), int(params["year"]))
    return summary


def _generic(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Unknown shape: counts and scalar fields only, never a dump of rows."""
    if isinstance(payload, list):
        rows = _rows(payload)
        return {"count": len(payload), "fields": sorted(rows[0]) if rows else []}
    if isinstance(payload, dict):
        scalars = {}
        for key, value in list(payload.items())[:30]:
            if isinstance(value, bool) or isinstance(value, (int, float)):
                scalars[key] = value
            elif isinstance(value, str):
                scalars[key] = value[:MAX_TEXT_CHARS]
            elif isinstance(value, list):
                scalars[f"{key}_count"] = len(value)
        return scalars
    return {"value": str(payload)[:MAX_TEXT_CHARS]}


SUMMARISERS: dict[str, Callable[[Any, dict[str, Any]], dict[str, Any]]] = {
    "/api/budgets/summary": _budget_summary,
    "/api/transactions/spending": _spending,
    "/api/budgets": _budgets,
    "/api/budgets/insights": _insights,
    "/api/categories": _categories,
    "/api/accounts": _accounts,
    "/api/loans": _loans,
    "/api/alerts": _alerts,
    "/api/rules": _rules,
    "/api/transactions": _transactions,
}
