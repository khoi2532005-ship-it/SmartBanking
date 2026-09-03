from datetime import date

from flask import Blueprint, jsonify, request

from services import database_api
from services.loan_logic import build_schedule, evaluate_eligibility


loans_bp = Blueprint("loans", __name__)

LOAN_TYPES = ("PERSONAL", "AUTO", "EDUCATION", "HOME", "BUSINESS")


@loans_bp.get("/api/loans")
def list_loans():
    filters = {
        "customer_id": request.args.get("customer_id"),
        "status": request.args.get("status"),
        "loan_type": request.args.get("loan_type"),
        "min_amount": request.args.get("min_amount"),
        "max_amount": request.args.get("max_amount"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "q": request.args.get("q"),
    }

    try:
        loans = database_api.search_loans(filters)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(loans)


@loans_bp.post("/api/loans")
def submit_loan():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    loan_type = str(data.get("loan_type", "")).strip().upper()
    if loan_type not in LOAN_TYPES:
        return jsonify({"error": f"loan_type must be one of {', '.join(LOAN_TYPES)}"}), 400

    try:
        float(data["requested_amount"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "requested_amount must be a number"}), 400

    customer_id = data.get("customer_id")
    if customer_id in (None, ""):
        return jsonify({"error": "customer_id is required"}), 400

    loan_data = {
        "customer_id": customer_id,
        "loan_type": loan_type,
        "requested_amount": data.get("requested_amount"),
        "loan_purpose": data.get("loan_purpose"),
        "application_date": data.get("application_date") or date.today().isoformat(),
        "status": "PENDING",
        "interest_rate": None,
        "approved_amount": None,
    }

    assessment = evaluate_eligibility(loan_data)
    loan_data["interest_rate"] = assessment.get("proposed_interest_rate")

    db_payload = {k: v for k, v in loan_data.items() if k in (
        "customer_id", "loan_type", "requested_amount", "loan_purpose",
        "application_date", "status", "interest_rate", "approved_amount",
    )}

    try:
        loan = database_api.create_loan(db_payload)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"loan": loan, "eligibility": assessment}), 201


@loans_bp.get("/api/loans/<int:loan_id>")
def get_loan(loan_id):
    try:
        response = database_api.get_loan_response(loan_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Loan application not found"}), 404
    response.raise_for_status()
    return jsonify(response.json())


@loans_bp.put("/api/loans/<int:loan_id>")
def update_loan(loan_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {
        "customer_id",
        "loan_type",
        "requested_amount",
        "loan_purpose",
        "application_date",
        "status",
        "interest_rate",
        "approved_amount",
    }
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    try:
        existing = database_api.get_loan_response(loan_id)
        if existing.status_code == 404:
            return jsonify({"error": "Loan application not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_loan(loan_id, updates)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@loans_bp.delete("/api/loans/<int:loan_id>")
def delete_loan(loan_id):
    try:
        existing = database_api.get_loan_response(loan_id)
        if existing.status_code == 404:
            return jsonify({"error": "Loan application not found"}), 404
        existing.raise_for_status()

        loan = existing.json()
        if loan["status"] == "APPROVED":
            return (
                jsonify(
                    {
                        "error": "Approved loans cannot be deleted. Set status to CANCELLED first."
                    }
                ),
                409,
            )

        database_api.delete_loan(loan_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": loan_id})


@loans_bp.get("/api/loans/<int:loan_id>/eligibility")
def loan_eligibility(loan_id):
    try:
        response = database_api.get_loan_response(loan_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Loan application not found"}), 404
    response.raise_for_status()

    loan = response.json()
    assessment = evaluate_eligibility(loan)
    return jsonify({"loan_id": loan_id, "status": loan["status"], "eligibility": assessment})


@loans_bp.post("/api/loans/<int:loan_id>/decision")
def decide_loan(loan_id):
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).strip().upper()

    if action not in ("APPROVE", "REJECT"):
        return jsonify({"error": 'action must be "APPROVE" or "REJECT"'}), 400

    try:
        response = database_api.get_loan_response(loan_id)
        if response.status_code == 404:
            return jsonify({"error": "Loan application not found"}), 404
        response.raise_for_status()
        loan = response.json()

        if loan["status"] != "PENDING":
            return jsonify({"error": f"Loan is already {loan['status']}"}), 409

        assessment = evaluate_eligibility(loan)

        if action == "REJECT":
            updated = database_api.update_loan(loan_id, {"status": "REJECTED"})
            return jsonify({"loan": updated, "reasons": [c for c in assessment["checks"] if not c["passed"]]})

        if not assessment["eligible"]:
            return (
                jsonify(
                    {
                        "error": "Loan is not eligible; use action REJECT.",
                        "failed_checks": [c for c in assessment["checks"] if not c["passed"]],
                    }
                ),
                409,
            )

        approved_amount = min(float(loan["requested_amount"]), assessment["max_allowed_amount"])
        rate = assessment["proposed_interest_rate"]
        term = assessment["proposed_term_months"]

        start = date.fromisoformat(str(loan["application_date"])[:10])
        schedule = [
            {**row, "loan_id": loan_id}
            for row in build_schedule(approved_amount, rate, term, start)
        ]

        created_repayments = database_api.create_repayments(schedule)
        try:
            updated = database_api.update_loan(
                loan_id,
                {
                    "status": "APPROVED",
                    "interest_rate": rate,
                    "approved_amount": approved_amount,
                },
            )
        except Exception:
            for repayment in created_repayments:
                try:
                    database_api.delete_repayment(repayment["repayment_id"])
                except Exception:
                    pass
            raise
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(
        {
            "loan": updated,
            "repayments_created": len(created_repayments),
            "first_due_date": created_repayments[0]["due_date"],
            "monthly_payment": created_repayments[0]["payment_amount"],
        }
    )
