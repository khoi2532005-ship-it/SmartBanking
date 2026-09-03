import json

from flask import Blueprint, jsonify

from services import database_api
from services.account_logic import evaluate_risk, summarize_accounts
from services.llm_client import create_chat_completion
from services.prompt_loader import load_prompt


ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")

PROMPT_DIR = "accounts"


def _ask(system_file, task_file, context, max_tokens=600):
    answer = create_chat_completion(
        [
            {"role": "system", "content": load_prompt(f"{PROMPT_DIR}/{system_file}")},
            {
                "role": "user",
                "content": f"{load_prompt(f'{PROMPT_DIR}/{task_file}')}\n\nData:\n{context}",
            },
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    return answer.strip()


def _fetch_customer_and_accounts(customer_id):
    response = database_api.get_customer_response(customer_id)
    if response.status_code == 404:
        return None, None
    response.raise_for_status()
    customer = response.json()
    accounts = database_api.search_accounts({"customer_id": customer_id})
    return customer, accounts


@ai_bp.get("/customers/<int:customer_id>/summary")
def account_summary(customer_id):
    try:
        customer, accounts = _fetch_customer_and_accounts(customer_id)
        if customer is None:
            return jsonify({"error": "Customer not found"}), 404

        totals = summarize_accounts(accounts)
        context = json.dumps({"customer": customer, "accounts": accounts, "totals": totals})
        explanation = _ask("explanation_system.txt", "summary_task.txt", context)
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    try:
        database_api.create_ai_summary(
            {
                "customer_id": customer_id,
                "summary_type": "ACCOUNT_SUMMARY",
                "summary_text": explanation,
            }
        )
    except Exception:
        pass  # AI-Mode should still respond even if saving the history fails

    return jsonify({"customer_id": customer_id, "summary": explanation, "totals": totals})


@ai_bp.get("/customers/<int:customer_id>/risk-profile")
def risk_profile(customer_id):
    try:
        customer, accounts = _fetch_customer_and_accounts(customer_id)
        if customer is None:
            return jsonify({"error": "Customer not found"}), 404

        assessment = evaluate_risk(customer, accounts)
        context = json.dumps({"customer": customer, "accounts": accounts, "assessment": assessment})
        explanation = _ask("explanation_system.txt", "risk_task.txt", context)
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    try:
        database_api.create_ai_summary(
            {
                "customer_id": customer_id,
                "summary_type": "RISK_PROFILE",
                "summary_text": explanation,
                "risk_level": assessment["risk_level"],
            }
        )
    except Exception:
        pass

    return jsonify(
        {
            "customer_id": customer_id,
            "risk_level": assessment["risk_level"],
            "checks": assessment["checks"],
            "explanation": explanation,
        }
    )


@ai_bp.get("/customers/<int:customer_id>/history")
def summary_history(customer_id):
    try:
        summaries = database_api.search_ai_summaries({"customer_id": customer_id})
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(summaries)
