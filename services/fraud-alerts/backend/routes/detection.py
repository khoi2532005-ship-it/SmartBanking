import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from services import database_api
from services.explain import generate_explanation
from services.rule_engine import evaluate
from services.transactions_source import fetch_transactions

detection_bp = Blueprint("detection", __name__)

logger = logging.getLogger("fraud.detection")

# Auto-explaining every hit means one LLM call per alert, which is slow and
# needs an API key just to run detection at all. Explain a handful inline (so
# the Act/Observe/Adapt loop visibly fires with a real LLM call) and leave the
# rest for on-demand /api/ai/alerts/<id>/explain from the AI-mode tab.
AUTO_EXPLAIN_LIMIT = 3


@detection_bp.post("/api/detection/run")
def run_detection():
    # Plan: pick enabled rules + the transaction window to scan.
    try:
        rules = database_api.search_rules({"enabled": "true"})
    except Exception as exc:
        return jsonify({"error": f"fraud-database-service unavailable: {exc}"}), 503

    logger.info("Plan: evaluating %d enabled rules", len(rules))

    # Act: load transactions (seed by default, or live Transactions API with a
    # seed fallback if unreachable), evaluate against the rules, insert new
    # alerts, explain a few of them.
    transactions, degraded = fetch_transactions()
    logger.info("Act: scanning %d transactions (degraded=%s)", len(transactions), degraded)

    hits = evaluate(transactions, rules)

    new_alerts = []
    skipped_duplicates = 0
    explanations_skipped = 0

    for rule, txn in hits:
        payload = {
            "rule_id": rule["rule_id"],
            "customer_id": txn["customer_id"],
            "transaction_id": txn["transaction_id"],
            "transaction_amount": txn["amount"],
            "transaction_recipient": txn.get("recipient_name"),
            "transaction_datetime": txn.get("datetime_sent"),
            "transaction_category": txn.get("generated_category"),
            "severity": rule["severity"],
            "status": "new",
        }

        try:
            response = database_api.create_alert_response(payload)
        except Exception as exc:
            logger.warning(
                "Act: failed to create alert for rule %s / txn %s: %s",
                rule["rule_id"], txn["transaction_id"], exc,
            )
            continue

        if response.status_code == 409:
            skipped_duplicates += 1
            continue
        response.raise_for_status()
        alert_id = response.json()["alert_id"]
        full_alert = {**payload, "alert_id": alert_id}

        if len(new_alerts) < AUTO_EXPLAIN_LIMIT:
            # Observe + Adapt happen inside generate_explanation itself.
            explanation, explanation_degraded = generate_explanation(full_alert, rule)
            if explanation_degraded:
                explanations_skipped += 1
            else:
                try:
                    database_api.update_alert(alert_id, {
                        "ai_explanation": explanation,
                        "explanation_generated_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    pass  # alert itself is still valid even if the explanation didn't persist
                full_alert["ai_explanation"] = explanation

        new_alerts.append(full_alert)

    result = {
        "evaluated": len(transactions),
        "rules_applied": len(rules),
        "new_alerts": new_alerts,
        "new_alert_count": len(new_alerts),
        "skipped_duplicates": skipped_duplicates,
        "explanations_skipped": explanations_skipped,
        "degraded": degraded,
    }
    logger.info("Observe/Adapt: %s", result)
    return jsonify(result)
