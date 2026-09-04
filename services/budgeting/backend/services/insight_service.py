"""AI insight generation, shared by the JSON API and the HTMX UI routes.

Each function returns (payload, status_code) so callers can relay the result
without duplicating any of the LLM or budget-analysis logic. The LLM is
reached through services.llm_client (Gemini by default).
"""

import json
from datetime import date

from services import database_api, transactions_client
from services.budget_logic import build_summary, evaluate_budget
from services.llm_client import create_chat_completion, get_model
from services.prompt_loader import load_prompt


PROMPT_DIR = "budgeting"


def current_period():
    today = date.today()
    return today.month, today.year


def _ask(task_file, context, max_tokens=500):
    messages = [
        {"role": "system", "content": load_prompt(f"{PROMPT_DIR}/insight_system.txt")},
        {
            "role": "user",
            "content": f"{load_prompt(f'{PROMPT_DIR}/{task_file}')}"
            f"\n\nBudget data (JSON):\n{context}",
        },
    ]
    return create_chat_completion(messages, max_tokens=max_tokens)


def _store(budget_id, insight_text, model_used):
    """Persist an insight; a storage failure must not lose the insight itself."""
    try:
        return database_api.create_insight(
            {
                "budget_id": budget_id,
                "insight_text": insight_text,
                "model_used": model_used,
            }
        )
    except Exception:
        return {}


def monthly_insight(customer_id, month, year):
    """Generate a whole-of-month spending insight for one customer."""
    try:
        customer_id = int(customer_id)
        month = int(month)
        year = int(year)
    except (TypeError, ValueError) as exc:
        return {"error": f"Invalid input: {exc}"}, 400

    budgets = database_api.search_budgets(
        {"customer_id": customer_id, "month": month, "year": year}
    )

    if not budgets:
        return (
            {
                "error": f"No budgets found for customer {customer_id} in "
                f"{month:02d}/{year}. Create a budget first."
            },
            404,
        )

    spend_totals, source, _ = transactions_client.spend_by_category(
        customer_id, month, year
    )
    summary = build_summary(budgets, spend_totals)

    context = json.dumps(
        {
            "month": month,
            "year": year,
            "totals": summary["totals"],
            "categories": [
                {
                    "category": line["category"],
                    "monthly_limit": line["monthly_limit"],
                    "spent": line["spent"],
                    "remaining": line["remaining"],
                    "percent_used": line["percent_used"],
                    "status": line["status"],
                }
                for line in summary["budgets"]
            ],
            "unbudgeted_spending": summary["unbudgeted_spending"],
        },
        indent=2,
    )

    try:
        insight_text = _ask("insight_task.txt", context, max_tokens=600)
    except Exception as exc:
        return {"error": f"AI request failed: {exc}"}, 503

    # Anchor the insight to the worst offender, else the busiest category.
    over = [line for line in summary["budgets"] if line["over_budget"]]
    anchor = (
        max(over, key=lambda line: line["over_by"])
        if over
        else max(summary["budgets"], key=lambda line: line["percent_used"])
    )

    model_used = get_model()
    stored = _store(anchor["budget_id"], insight_text, model_used)

    return (
        {
            "customer_id": customer_id,
            "month": month,
            "year": year,
            "model_used": model_used,
            "spending_source": source,
            "insight": insight_text,
            "anchor_budget_id": anchor["budget_id"],
            "insight_id": stored.get("insight_id"),
            "totals": summary["totals"],
            "over_budget_categories": summary["over_budget_categories"],
        },
        200,
    )


def explain_budget(budget_id):
    """Explain why one category is over or under its limit."""
    response = database_api.get_budget_response(budget_id)
    if response.status_code == 404:
        return {"error": "Budget not found"}, 404
    response.raise_for_status()
    budget = response.json()

    spend_totals, source, transactions = transactions_client.spend_by_category(
        budget["customer_id"], budget["month"], budget["year"]
    )
    detail = evaluate_budget(budget, spend_totals.get(budget["category"], 0.0))

    context = json.dumps(
        {
            "budget": detail,
            "transactions": [
                {
                    "date": t["transaction_date"],
                    "description": t["description"],
                    "amount": t["amount"],
                }
                for t in transactions
                if t.get("category") == budget["category"]
            ],
        },
        indent=2,
    )

    try:
        insight_text = _ask("explain_task.txt", context, max_tokens=450)
    except Exception as exc:
        return {"error": f"AI request failed: {exc}"}, 503

    model_used = get_model()
    stored = _store(budget_id, insight_text, model_used)

    return (
        {
            "budget_id": budget_id,
            "category": budget["category"],
            "status": detail["status"],
            "spent": detail["spent"],
            "monthly_limit": detail["monthly_limit"],
            "model_used": model_used,
            "spending_source": source,
            "insight": insight_text,
            "insight_id": stored.get("insight_id"),
        },
        200,
    )
