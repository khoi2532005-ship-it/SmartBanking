from flask import Blueprint, jsonify, request

from services import database_api
from services.constants import ALERT_STATUSES
from services.validation import ValidationError, choice, validate_alert_filters, validate_new_alert

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

    try:
        payload = validate_new_alert(data)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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
    try:
        filters = validate_alert_filters(request.args)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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

    # Status is the only field a caller may change (spec: "Update: alert
    # status"). The AI explanation is written by this service itself, through
    # database_api directly, so the public API cannot put arbitrary text there.
    if "status" not in data:
        return jsonify({"error": "No updatable fields provided. Allowed: status"}), 400
    try:
        updates = {"status": choice(data["status"], "status", ALERT_STATUSES)}
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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
