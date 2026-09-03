"""AI-Mode JSON API: Frontend -> Backend/API -> Ollama -> LLM."""

from flask import Blueprint, jsonify, request

from services import database_api, insight_service


insights_bp = Blueprint("insights", __name__)


@insights_bp.post("/api/budgets/insight")
def generate_insight():
    data = request.get_json(silent=True) or {}
    month, year = insight_service.current_period()

    payload, status = insight_service.monthly_insight(
        customer_id=data.get("customer_id", 1),
        month=data.get("month") or month,
        year=data.get("year") or year,
    )
    return jsonify(payload), status


@insights_bp.post("/api/budgets/<int:budget_id>/explain")
def explain_budget(budget_id):
    payload, status = insight_service.explain_budget(budget_id)
    return jsonify(payload), status


@insights_bp.get("/api/budgets/insights")
def list_insights():
    filters = {
        "budget_id": request.args.get("budget_id"),
        "customer_id": request.args.get("customer_id"),
        "limit": request.args.get("limit", 20),
    }
    return jsonify(database_api.search_insights(filters))


@insights_bp.delete("/api/budgets/insights/<int:insight_id>")
def delete_insight(insight_id):
    response = database_api.delete_insight(insight_id)
    body = response.json() if response.content else {}
    return jsonify(body), response.status_code
