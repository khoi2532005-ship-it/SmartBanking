from datetime import date, timedelta

from flask import Blueprint, jsonify, request
import requests

from services import database_api


repayments_bp = Blueprint("repayments", __name__)


@repayments_bp.get("/api/repayments")
def list_repayments():
    filters = {
        "loan_id": request.args.get("loan_id"),
        "payment_status": request.args.get("payment_status"),
        "due_before": request.args.get("due_before"),
        "due_after": request.args.get("due_after"),
        "overdue": request.args.get("overdue"),
        "unpaid": request.args.get("unpaid"),
    }

    try:
        repayments = database_api.search_repayments(filters)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(repayments)


@repayments_bp.get("/api/repayments/upcoming")
def upcoming_repayments():
    days = request.args.get("days", default=30, type=int)
    horizon = (date.today() + timedelta(days=days)).isoformat()

    try:
        repayments = database_api.search_repayments(
            {"due_before": horizon, "unpaid": "true"}
        )
        loans = {loan["loan_id"]: loan for loan in database_api.search_loans()}
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    results = []
    for repayment in repayments:
        entry = dict(repayment)
        loan = loans.get(repayment["loan_id"])
        if loan:
            entry["customer_id"] = loan["customer_id"]
            entry["loan_type"] = loan["loan_type"]
        due = date.fromisoformat(str(repayment["due_date"])[:10])
        entry["days_until_due"] = (due - date.today()).days
        results.append(entry)

    return jsonify(results)


@repayments_bp.get("/api/repayments/<int:repayment_id>")
def get_repayment(repayment_id):
    try:
        repayment = database_api.get_repayment(repayment_id)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 503
        message = "Repayment not found" if status == 404 else f"database-service unavailable: {exc}"
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(repayment)


@repayments_bp.put("/api/repayments/<int:repayment_id>")
def update_repayment(repayment_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {
        "due_date",
        "payment_amount",
        "principal_amount",
        "interest_amount",
        "amount_paid",
        "payment_date",
        "payment_status",
    }
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    try:
        existing = database_api.get_repayment(repayment_id)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 503
        message = "Repayment not found" if status == 404 else f"database-service unavailable: {exc}"
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if updates.get("amount_paid") is not None and updates.get("payment_status") is None:
        paid = float(updates["amount_paid"])
        if paid >= float(existing["payment_amount"]):
            updates["payment_status"] = "PAID"
            updates.setdefault("payment_date", date.today().isoformat())
        elif paid > 0:
            updates["payment_status"] = "PARTIAL"

    try:
        updated = database_api.update_repayment(repayment_id, updates)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@repayments_bp.delete("/api/repayments/<int:repayment_id>")
def delete_repayment(repayment_id):
    try:
        database_api.get_repayment(repayment_id)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 503
        message = "Repayment not found" if status == 404 else f"database-service unavailable: {exc}"
        return jsonify({"error": message}), status
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    try:
        database_api.delete_repayment(repayment_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": repayment_id})
