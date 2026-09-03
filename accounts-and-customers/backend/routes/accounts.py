from flask import Blueprint, jsonify, request

from services import database_api
from services.account_logic import ACCOUNT_STATUSES, ACCOUNT_TYPES


accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.get("/api/accounts")
def list_accounts():
    filters = {
        "customer_id": request.args.get("customer_id"),
        "status": request.args.get("status"),
        "account_type": request.args.get("account_type"),
        "min_balance": request.args.get("min_balance"),
        "max_balance": request.args.get("max_balance"),
        "q": request.args.get("q"),
    }

    try:
        accounts = database_api.search_accounts(filters)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(accounts)


@accounts_bp.post("/api/accounts")
def create_account():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    customer_id = data.get("customer_id")
    if customer_id in (None, ""):
        return jsonify({"error": "customer_id is required"}), 400

    account_type = str(data.get("account_type", "")).strip().upper()
    if account_type not in ACCOUNT_TYPES:
        return jsonify({"error": f"account_type must be one of {', '.join(ACCOUNT_TYPES)}"}), 400

    account_number = str(data.get("account_number", "")).strip()
    if not account_number:
        return jsonify({"error": "account_number is required"}), 400

    try:
        balance = float(data.get("balance", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "balance must be a number"}), 400

    payload = {
        "customer_id": customer_id,
        "account_number": account_number,
        "account_type": account_type,
        "balance": balance,
        "currency": data.get("currency", "AUD"),
        "status": "ACTIVE",
    }

    try:
        result = database_api.create_account(payload)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            return jsonify({"error": "Customer not found"}), 404
        if status == 409:
            return jsonify({"error": "An account with this account_number already exists"}), 409
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(result), 201


@accounts_bp.get("/api/accounts/<int:account_id>")
def get_account(account_id):
    try:
        response = database_api.get_account_response(account_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Account not found"}), 404
    response.raise_for_status()
    return jsonify(response.json())


@accounts_bp.put("/api/accounts/<int:account_id>")
def update_account(account_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {"account_type", "balance", "currency", "status"}
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    if "account_type" in updates:
        updates["account_type"] = str(updates["account_type"]).strip().upper()
        if updates["account_type"] not in ACCOUNT_TYPES:
            return jsonify({"error": f"account_type must be one of {', '.join(ACCOUNT_TYPES)}"}), 400

    if "status" in updates:
        updates["status"] = str(updates["status"]).strip().upper()
        if updates["status"] not in ACCOUNT_STATUSES:
            return jsonify({"error": f"status must be one of {', '.join(ACCOUNT_STATUSES)}"}), 400

    if "balance" in updates:
        try:
            updates["balance"] = float(updates["balance"])
        except (TypeError, ValueError):
            return jsonify({"error": "balance must be a number"}), 400

    try:
        existing = database_api.get_account_response(account_id)
        if existing.status_code == 404:
            return jsonify({"error": "Account not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_account(account_id, updates)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@accounts_bp.post("/api/accounts/<int:account_id>/close")
def close_account(account_id):
    try:
        existing = database_api.get_account_response(account_id)
        if existing.status_code == 404:
            return jsonify({"error": "Account not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_account(account_id, {"status": "CLOSED"})
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@accounts_bp.delete("/api/accounts/<int:account_id>")
def delete_account(account_id):
    try:
        existing = database_api.get_account_response(account_id)
        if existing.status_code == 404:
            return jsonify({"error": "Account not found"}), 404
        existing.raise_for_status()

        account = existing.json()
        if float(account.get("balance") or 0) != 0:
            return (
                jsonify(
                    {
                        "error": "Account balance must be zero before it can be deleted. "
                        "Transfer or withdraw the remaining balance first."
                    }
                ),
                409,
            )

        database_api.delete_account(account_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": account_id})
