from datetime import date

from flask import Blueprint, jsonify, request

from services import database_api, transactions_client
from services.budget_logic import build_summary, evaluate_budget


budgets_bp = Blueprint("budgets", __name__)

REQUIRED_FIELDS = ("customer_id", "category", "monthly_limit")


def _current_period():
    today = date.today()
    return today.month, today.year


def _period_from_args(args):
    month, year = _current_period()
    return int(args.get("month") or month), int(args.get("year") or year)


def _passthrough(response):
    """Relay a database-service response, preserving its status code."""
    body = response.json() if response.content else {}
    return jsonify(body), response.status_code


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

@budgets_bp.get("/api/budgets")
def list_budgets():
    filters = {
        "customer_id": request.args.get("customer_id"),
        "category": request.args.get("category"),
        "month": request.args.get("month"),
        "year": request.args.get("year"),
    }
    return jsonify(database_api.search_budgets(filters))


@budgets_bp.get("/api/budgets/summary")
def budget_summary():
    """Budgets for a period, enriched with actual spend from the Transactions API."""
    customer_id = request.args.get("customer_id", 1)
    month, year = _period_from_args(request.args)

    budgets = database_api.search_budgets(
        {"customer_id": customer_id, "month": month, "year": year}
    )

    spend_totals, source, _ = transactions_client.spend_by_category(
        customer_id, month, year
    )

    summary = build_summary(budgets, spend_totals)
    summary.update(
        {
            "customer_id": int(customer_id),
            "month": month,
            "year": year,
            "spending_source": source,
        }
    )
    return jsonify(summary)


@budgets_bp.get("/api/budgets/<int:budget_id>")
def get_budget(budget_id):
    response = database_api.get_budget_response(budget_id)
    if response.status_code == 404:
        return jsonify({"error": "Budget not found"}), 404
    response.raise_for_status()

    budget = response.json()
    spend_totals, source, transactions = transactions_client.spend_by_category(
        budget["customer_id"], budget["month"], budget["year"]
    )

    detail = evaluate_budget(budget, spend_totals.get(budget["category"], 0.0))
    detail["spending_source"] = source
    detail["transactions"] = [
        t for t in transactions if t.get("category") == budget["category"]
    ]
    detail["created_at"] = budget.get("created_at")
    return jsonify(detail)


@budgets_bp.get("/api/categories")
def list_categories():
    return jsonify(database_api.search_categories())


@budgets_bp.get("/api/transactions/spending")
def spending_breakdown():
    """Exposes what this feature reads from the Transactions API, for the demo."""
    customer_id = request.args.get("customer_id", 1)
    month, year = _period_from_args(request.args)

    totals, source, transactions = transactions_client.spend_by_category(
        customer_id, month, year
    )
    return jsonify(
        {
            "customer_id": int(customer_id),
            "month": month,
            "year": year,
            "spending_source": source,
            "totals_by_category": totals,
            "transaction_count": len(transactions),
        }
    )


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@budgets_bp.post("/api/budgets")
def create_budget():
    data = request.get_json(silent=True) or {}

    for field in REQUIRED_FIELDS:
        if data.get(field) in (None, ""):
            return jsonify({"error": f"{field} required"}), 400

    try:
        monthly_limit = float(data["monthly_limit"])
        customer_id = int(data["customer_id"])
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid input: {exc}"}), 400

    if monthly_limit <= 0:
        return jsonify({"error": "monthly_limit must be greater than zero"}), 400

    month, year = _current_period()
    payload = {
        "customer_id": customer_id,
        "category": str(data["category"]).strip(),
        "monthly_limit": round(monthly_limit, 2),
        "month": int(data.get("month") or month),
        "year": int(data.get("year") or year),
    }

    if not 1 <= payload["month"] <= 12:
        return jsonify({"error": "month must be between 1 and 12"}), 400

    return _passthrough(database_api.create_budget(payload))


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@budgets_bp.put("/api/budgets/<int:budget_id>")
def update_budget(budget_id):
    data = request.get_json(silent=True) or {}

    payload = {}

    if "monthly_limit" in data:
        try:
            monthly_limit = float(data["monthly_limit"])
        except (TypeError, ValueError) as exc:
            return jsonify({"error": f"Invalid monthly_limit: {exc}"}), 400
        if monthly_limit <= 0:
            return jsonify({"error": "monthly_limit must be greater than zero"}), 400
        payload["monthly_limit"] = round(monthly_limit, 2)

    if data.get("category"):
        payload["category"] = str(data["category"]).strip()

    for field in ("month", "year", "customer_id"):
        if data.get(field) not in (None, ""):
            try:
                payload[field] = int(data[field])
            except (TypeError, ValueError) as exc:
                return jsonify({"error": f"Invalid {field}: {exc}"}), 400

    if "month" in payload and not 1 <= payload["month"] <= 12:
        return jsonify({"error": "month must be between 1 and 12"}), 400

    if not payload:
        return jsonify({"error": "No updatable fields supplied"}), 400

    return _passthrough(database_api.update_budget(budget_id, payload))


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

@budgets_bp.delete("/api/budgets/<int:budget_id>")
def delete_budget(budget_id):
    return _passthrough(database_api.delete_budget(budget_id))
