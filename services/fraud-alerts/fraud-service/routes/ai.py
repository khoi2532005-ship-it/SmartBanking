from datetime import datetime, timezone

from flask import Blueprint, jsonify

from services import database_api
from services.explain import generate_explanation

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


@ai_bp.get("/alerts/<int:alert_id>/explain")
def explain_alert(alert_id):
    try:
        response = database_api.get_alert_response(alert_id)
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    if response.status_code == 404:
        return jsonify({"error": "Alert not found"}), 404
    response.raise_for_status()
    alert = response.json()

    try:
        rule = database_api.get_rule(alert["rule_id"])
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    explanation, degraded = generate_explanation(alert, rule)

    if not degraded:
        try:
            database_api.update_alert(alert_id, {
                "ai_explanation": explanation,
                "explanation_generated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass  # explanation still returned to the caller even if it didn't persist

    return jsonify({"alert_id": alert_id, "explanation": explanation, "degraded": degraded})
