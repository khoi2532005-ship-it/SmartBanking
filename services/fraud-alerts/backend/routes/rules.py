from flask import Blueprint, jsonify, request

from services import database_api
from services.constants import RULE_TYPES, SEVERITIES

rules_bp = Blueprint("rules", __name__)


@rules_bp.get("/api/rules")
def list_rules():
    filters = {
        "rule_type": request.args.get("rule_type"),
        "enabled": request.args.get("enabled"),
    }
    try:
        rules = database_api.search_rules(filters)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503
    return jsonify(rules)


@rules_bp.post("/api/rules")
def submit_rule():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    rule_type = str(data.get("rule_type", "")).strip().lower()
    if rule_type not in RULE_TYPES:
        return jsonify({"error": f"rule_type must be one of {', '.join(RULE_TYPES)}"}), 400

    severity = str(data.get("severity", "")).strip().lower()
    if severity not in SEVERITIES:
        return jsonify({"error": f"severity must be one of {', '.join(SEVERITIES)}"}), 400

    if not data.get("rule_name"):
        return jsonify({"error": "rule_name is required"}), 400

    try:
        float(data.get("threshold_value"))
    except (TypeError, ValueError):
        return jsonify({"error": "threshold_value must be a number"}), 400

    payload = {
        "rule_name": data.get("rule_name"),
        "rule_type": rule_type,
        "threshold_value": data.get("threshold_value"),
        "threshold_secondary": data.get("threshold_secondary"),
        "severity": severity,
        "enabled": data.get("enabled", 1),
    }

    try:
        rule = database_api.create_rule(payload)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify(rule), 201


@rules_bp.get("/api/rules/<int:rule_id>")
def get_rule(rule_id):
    try:
        response = database_api.get_rule_response(rule_id)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Rule not found"}), 404
    response.raise_for_status()
    return jsonify(response.json())


@rules_bp.put("/api/rules/<int:rule_id>")
def update_rule(rule_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    allowed = {"rule_name", "rule_type", "threshold_value", "threshold_secondary", "severity", "enabled"}
    updates = {key: value for key, value in data.items() if key in allowed}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(allowed))}"}), 400

    if "rule_type" in updates:
        updates["rule_type"] = str(updates["rule_type"]).strip().lower()
        if updates["rule_type"] not in RULE_TYPES:
            return jsonify({"error": f"rule_type must be one of {', '.join(RULE_TYPES)}"}), 400

    if "severity" in updates:
        updates["severity"] = str(updates["severity"]).strip().lower()
        if updates["severity"] not in SEVERITIES:
            return jsonify({"error": f"severity must be one of {', '.join(SEVERITIES)}"}), 400

    try:
        existing = database_api.get_rule_response(rule_id)
        if existing.status_code == 404:
            return jsonify({"error": "Rule not found"}), 404
        existing.raise_for_status()

        updated = database_api.update_rule(rule_id, updates)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@rules_bp.delete("/api/rules/<int:rule_id>")
def delete_rule(rule_id):
    try:
        existing = database_api.get_rule_response(rule_id)
        if existing.status_code == 404:
            return jsonify({"error": "Rule not found"}), 404
        existing.raise_for_status()

        database_api.delete_rule(rule_id)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": rule_id})
