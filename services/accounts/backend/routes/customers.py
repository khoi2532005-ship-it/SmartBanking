from flask import Blueprint, jsonify, request

from services import database_api


customers_bp = Blueprint("customers", __name__)


@customers_bp.get("/api/customers")
def list_customers():
    filters = {
        "q": request.args.get("q"),
        "email": request.args.get("email"),
    }

    try:
        customers = database_api.search_customers(filters)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(customers)


@customers_bp.post("/api/customers")
def create_customer():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    for field in ("first_name", "last_name", "email"):
        if not str(data.get(field, "")).strip():
            return jsonify({"error": f"{field} is required"}), 400

    email = str(data["email"]).strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "email must be a valid email address"}), 400

    payload = {
        "first_name": str(data["first_name"]).strip(),
        "last_name": str(data["last_name"]).strip(),
        "email": email,
        "phone": data.get("phone"),
        "date_of_birth": data.get("date_of_birth"),
        "address": data.get("address"),
    }

    try:
        result = database_api.create_customer(payload)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 409:
            return jsonify({"error": "A customer with this email already exists"}), 409
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(result), 201


@customers_bp.get("/api/customers/<int:customer_id>")
def get_customer(customer_id):
    try:
        response = database_api.get_customer_response(customer_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Customer not found"}), 404
    response.raise_for_status()
    customer = response.json()

    try:
        customer["accounts"] = database_api.search_accounts({"customer_id": customer_id})
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(customer)


@customers_bp.put("/api/customers/<int:customer_id>")
def update_customer(customer_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {"first_name", "last_name", "email", "phone", "date_of_birth", "address"}
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    if "email" in updates:
        email = str(updates["email"]).strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "email must be a valid email address"}), 400
        updates["email"] = email

    try:
        existing = database_api.get_customer_response(customer_id)
        if existing.status_code == 404:
            return jsonify({"error": "Customer not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_customer(customer_id, updates)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 409:
            return jsonify({"error": "A customer with this email already exists"}), 409
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@customers_bp.delete("/api/customers/<int:customer_id>")
def delete_customer(customer_id):
    try:
        existing = database_api.get_customer_response(customer_id)
        if existing.status_code == 404:
            return jsonify({"error": "Customer not found"}), 404
        existing.raise_for_status()

        accounts = database_api.search_accounts({"customer_id": customer_id})
        active_accounts = [a for a in accounts if str(a.get("status", "")).upper() == "ACTIVE"]
        if active_accounts:
            return (
                jsonify(
                    {
                        "error": "Customer has active accounts. Close all accounts before deleting the profile.",
                        "active_account_ids": [a["account_id"] for a in active_accounts],
                    }
                ),
                409,
            )

        database_api.delete_customer(customer_id)
    except Exception as exc:
        return jsonify({"error": f"database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": customer_id})
