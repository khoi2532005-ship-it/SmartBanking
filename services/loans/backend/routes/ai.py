from flask import Blueprint, jsonify, request

from services import database_api
from services.llm_client import create_chat_completion
from services.prompt_loader import load_prompt
from services.loan_logic import evaluate_eligibility, monthly_payment


ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")

PROMPT_DIR = "service/loans"


def _ask(system_file, task_file, context, max_tokens=1500):
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


def _fetch_loan_or_error(loan_id):
    response = database_api.get_loan_response(loan_id)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


@ai_bp.get("/loans/<int:loan_id>/explain-eligibility")
def explain_eligibility(loan_id):
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return jsonify({"error": "Loan application not found"}), 404
        assessment = evaluate_eligibility(loan)
        explanation = _ask(
            "explanation_system.txt",
            "eligibility_task.txt",
            jsonify({"loan": loan, "assessment": assessment}).get_data(as_text=True),
        )
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    return jsonify({"loan_id": loan_id, "eligible": assessment["eligible"], "explanation": explanation})


@ai_bp.get("/loans/<int:loan_id>/explain-decision")
def explain_decision(loan_id):
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return jsonify({"error": "Loan application not found"}), 404

        status = loan["status"]
        if status not in ("APPROVED", "REJECTED"):
            return (
                jsonify(
                    {
                        "error": f"Loan has not been decided yet (status {status}). "
                        "Decide it first via POST /api/loans/{id}/decision."
                    }
                ),
                409,
            )

        assessment = evaluate_eligibility(loan)
        explanation = _ask(
            "explanation_system.txt",
            "decision_task.txt",
            jsonify({"loan": loan, "assessment": assessment}).get_data(as_text=True),
            max_tokens=1500,
        )
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    return jsonify({"loan_id": loan_id, "status": status, "explanation": explanation})


@ai_bp.get("/loans/<int:loan_id>/explain-repayments")
def explain_repayments(loan_id):
    try:
        loan = _fetch_loan_or_error(loan_id)
        if loan is None:
            return jsonify({"error": "Loan application not found"}), 404

        repayments = database_api.search_repayments({"loan_id": loan_id})
        explanation = _ask(
            "explanation_system.txt",
            "repayment_task.txt",
            jsonify({"loan": loan, "repayments": repayments}).get_data(as_text=True),
        )
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    return jsonify({"loan_id": loan_id, "explanation": explanation})


@ai_bp.post("/repayment-options")
def compare_repayment_options():
    data = request.get_json(silent=True) or {}

    try:
        loan = None
        if data.get("loan_id") is not None:
            loan = _fetch_loan_or_error(int(data["loan_id"]))
            if loan is None:
                return jsonify({"error": "Loan application not found"}), 404

        amount = float(data.get("amount") or (loan or {}).get("approved_amount") or (loan or {}).get("requested_amount"))
        rate = float(data.get("interest_rate") or (loan or {}).get("interest_rate") or 8.5)
        income = data.get("monthly_income") or (loan or {}).get("monthly_income")
        terms = data.get("terms") or [12, 24, 36, 48, 60]
        terms = [int(t) for t in terms if int(t) > 0][:6]
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid input: {exc}"}), 400

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

    payload = {"amount_financed": amount, "annual_interest_rate_pct": rate, "options": options}
    if income:
        payload["monthly_income"] = income

    try:
        explanation = _ask(
            "explanation_system.txt",
            "comparison_task.txt",
            jsonify(payload).get_data(as_text=True),
            max_tokens=1500,
        )
    except Exception as exc:
        return jsonify({"error": f"AI request failed: {exc}"}), 503

    return jsonify({**payload, "recommendation": explanation})
