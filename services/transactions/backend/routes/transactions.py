from flask import Blueprint, jsonify, request

from services import database_api


transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.get("/api/transactions")
def list_transactions():
    filters = {
        "account_id": request.args.get("account_id"),
        "customer_id": request.args.get("customer_id"),
        "type": request.args.get("type"),
        "category": request.args.get("category"),
        "min_amount": request.args.get("min_amount"),
        "max_amount": request.args.get("max_amount"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "q": request.args.get("q"),
    }

    try:
        transactions = database_api.search_transactions(filters)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(transactions)


@transactions_bp.post("/api/transactions")
def create_transaction():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    required_fields = ["account_id", "amount", "currency", "type", "date"]
    for field in required_fields:
        if field not in data or data.get(field) in (None, ""):
            return jsonify({"error": f"{field} is required"}), 400

    try:
        amount = float(data["amount"])
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400

    payload = {
        "account_id": data["account_id"],
        "amount": amount,
        "currency": str(data["currency"]).strip().upper(),
        "type": str(data["type"]).strip(),
        "category": data.get("category"),
        "description": data.get("description"),
        "date": str(data["date"]).strip(),
    }

    try:
        result = database_api.create_transaction(payload)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            return jsonify({"error": "Account not found"}), 404
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(result), 201


@transactions_bp.get("/api/transactions/<int:transaction_id>")
def get_transaction(transaction_id):
    try:
        response = database_api.get_transaction_response(transaction_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Transaction not found"}), 404
    response.raise_for_status()
    return jsonify(response.json())


@transactions_bp.put("/api/transactions/<int:transaction_id>")
def update_transaction(transaction_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {"account_id", "amount", "currency", "type", "category", "description", "date"}
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    try:
        existing = database_api.get_transaction_response(transaction_id)
        if existing.status_code == 404:
            return jsonify({"error": "Transaction not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_transaction(transaction_id, updates)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@transactions_bp.delete("/api/transactions/<int:transaction_id>")
def delete_transaction(transaction_id):
    try:
        response = database_api.get_transaction_response(transaction_id)
        if response.status_code == 404:
            return jsonify({"error": "Transaction not found"}), 404
        response.raise_for_status()

        database_api.delete_transaction(transaction_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": transaction_id})


@transactions_bp.get("/api/customers")
def list_customers():
    try:
        return jsonify(database_api.search_customers())
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503


@transactions_bp.get("/api/accounts")
def list_accounts():
    try:
        return jsonify(database_api.search_accounts())
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503
