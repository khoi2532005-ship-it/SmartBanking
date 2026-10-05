import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from services import database_api
from services.explain import generate_explanation
from services.rule_engine import evaluate
from services.transactions_source import SourceUnavailable, fetch_transactions

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

    # Act: load transactions (the seed fixture, or the live Transactions API
    # with customers resolved through Accounts), evaluate them against the
    # rules, insert new alerts, explain a few of them.
    try:
        transactions, source, unscannable = fetch_transactions()
    except SourceUnavailable as exc:
        # Adapt: there is nothing trustworthy to scan, so stop before writing
        # anything and say why.
        logger.warning("Adapt: detection stopped before writing any alerts - %s", exc)
        return jsonify({"error": f"Detection did not run: {exc}. No alerts were written."}), 503
    logger.info("Act: scanning %d %s transactions (%d unscannable rows left out)",
                len(transactions), source, unscannable)

    skipped_rules = []
    hits = evaluate(transactions, rules, skipped_rules)
    if skipped_rules:
        logger.warning("Adapt: skipped rule(s) %s - their stored thresholds are not usable", skipped_rules)

    new_alerts = []
    skipped_duplicates = 0
    failed_writes = 0
    explanations_skipped = 0

    for rule, txn in hits:
        payload = {
            "rule_id": rule["rule_id"],
            "customer_id": txn["customer_id"],
            "transaction_id": txn["transaction_id"],
            "transaction_amount": txn["amount"],
            "transaction_recipient": txn.get("description"),
            "transaction_datetime": txn.get("date"),
            "transaction_category": txn.get("category"),
            "severity": rule["severity"],
            "status": "new",
        }

        try:
            response = database_api.create_alert_response(payload)
            if response.status_code == 409:
                skipped_duplicates += 1
                continue
            response.raise_for_status()
            alert_id = response.json()["alert_id"]
        except Exception as exc:
            # Count it and keep going - one failed insert used to raise out of
            # the loop as a 500 after earlier alerts had already been written.
            failed_writes += 1
            logger.warning(
                "Act: failed to create alert for rule %s / txn %s: %s",
                rule["rule_id"], txn["transaction_id"], exc,
            )
            continue
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
        "source": source,
        "evaluated": len(transactions),
        "unscannable_transactions": unscannable,
        "rules_applied": len(rules),
        "rules_skipped": skipped_rules,
        "new_alerts": new_alerts,
        "new_alert_count": len(new_alerts),
        "skipped_duplicates": skipped_duplicates,
        "failed_writes": failed_writes,
        "explanations_skipped": explanations_skipped,
    }
    logger.info(
        "Observe: %d new alert(s), %d duplicate(s) skipped, %d failed write(s), %d explanation(s) unavailable",
        len(new_alerts), skipped_duplicates, failed_writes, explanations_skipped,
    )
    return jsonify(result)
