from flask import Blueprint, jsonify, request

from services import database_api
from services.constants import ALERT_STATUSES, SEVERITIES

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.post("/api/alerts")
def submit_alert():
    """Manually create an alert record - normal detection creates alerts via
    routes/detection.py instead, this is for testing/seeding and for the
    spec's own "Create: alert record" CRUD requirement."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    required = ["rule_id", "customer_id", "transaction_id", "transaction_amount", "severity"]
    missing = [f for f in required if data.get(f) is None]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    severity = str(data.get("severity", "")).strip().lower()
    if severity not in SEVERITIES:
        return jsonify({"error": f"severity must be one of {', '.join(SEVERITIES)}"}), 400

    status = str(data.get("status", "new")).strip().lower()
    if status not in ALERT_STATUSES:
        return jsonify({"error": f"status must be one of {', '.join(ALERT_STATUSES)}"}), 400

    payload = {
        "rule_id": data.get("rule_id"),
        "customer_id": data.get("customer_id"),
        "transaction_id": data.get("transaction_id"),
        "transaction_amount": data.get("transaction_amount"),
        "transaction_recipient": data.get("transaction_recipient"),
        "transaction_datetime": data.get("transaction_datetime"),
        "transaction_category": data.get("transaction_category"),
        "severity": severity,
        "status": status,
    }

    try:
        response = database_api.create_alert_response(payload)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Rule not found"}), 404
    if response.status_code == 409:
        return jsonify(response.json()), 409
    response.raise_for_status()
    return jsonify(response.json()), 201


@alerts_bp.get("/api/alerts")
def list_alerts():
    filters = {
        "status": request.args.get("status"),
        "rule_id": request.args.get("rule_id"),
        "customer_id": request.args.get("customer_id"),
        "min_amount": request.args.get("min_amount"),
        "max_amount": request.args.get("max_amount"),
        "date_from": request.args.get("date_from"),
        "date_to": request.args.get("date_to"),
        "q": request.args.get("q"),
    }
    try:
        alerts = database_api.search_alerts(filters)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503
    return jsonify(alerts)


@alerts_bp.get("/api/alerts/<int:alert_id>")
def get_alert(alert_id):
    try:
        response = database_api.get_alert_response(alert_id)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Alert not found"}), 404
    response.raise_for_status()
    alert = response.json()

    # Alert rows only store rule_id - the detail view needs the rule's own
    # fields to explain what fired, so enrich here rather than making the
    # frontend do a second lookup.
    try:
        rule = database_api.get_rule(alert["rule_id"])
        alert["rule_name"] = rule.get("rule_name")
        alert["rule_type"] = rule.get("rule_type")
        alert["threshold_value"] = rule.get("threshold_value")
        alert["threshold_secondary"] = rule.get("threshold_secondary")
    except Exception:
        alert["rule_name"] = None
        alert["rule_type"] = None

    return jsonify(alert)


@alerts_bp.put("/api/alerts/<int:alert_id>")
def update_alert(alert_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    status = data.get("status")
    if status is not None:
        status = str(status).strip().lower()
        if status not in ALERT_STATUSES:
            return jsonify({"error": f"status must be one of {', '.join(ALERT_STATUSES)}"}), 400
        data = {**data, "status": status}

    allowed = {"status", "ai_explanation", "explanation_generated_at"}
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    try:
        existing = database_api.get_alert_response(alert_id)
        if existing.status_code == 404:
            return jsonify({"error": "Alert not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_alert(alert_id, updates)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@alerts_bp.delete("/api/alerts/<int:alert_id>")
def delete_alert(alert_id):
    try:
        existing = database_api.get_alert_response(alert_id)
        if existing.status_code == 404:
            return jsonify({"error": "Alert not found"}), 404
        existing.raise_for_status()

        database_api.delete_alert(alert_id)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": alert_id})
