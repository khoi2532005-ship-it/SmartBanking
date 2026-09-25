from flask import Blueprint, jsonify, request

from services import database_api
from services.validation import RULE_FIELDS, ValidationError, validate_rule

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

    try:
        payload = validate_rule(data)
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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

    updates = {key: value for key, value in data.items() if key in RULE_FIELDS}
    if not updates:
        return jsonify({"error": f"No updatable fields provided. Allowed: {', '.join(sorted(RULE_FIELDS))}"}), 400

    try:
        existing = database_api.get_rule_response(rule_id)
        if existing.status_code == 404:
            return jsonify({"error": "Rule not found"}), 404
        existing.raise_for_status()
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    try:
        payload = validate_rule(updates, existing=existing.json())
    except ValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        updated = database_api.update_rule(rule_id, payload)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify(updated)


@rules_bp.delete("/api/rules/<int:rule_id>")
def delete_rule(rule_id):
    try:
        response = database_api.delete_rule_response(rule_id)
        # 409: the rule still has alerts (enforced foreign key) - pass the
        # database service's explanation through rather than calling it "unavailable".
        if response.status_code in (404, 409):
            return jsonify(response.json()), response.status_code
        response.raise_for_status()
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    return jsonify({"deleted": rule_id})
