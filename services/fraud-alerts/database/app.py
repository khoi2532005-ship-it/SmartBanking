import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

DATABASE_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fraud.db")


def _init_sqlite():
    conn = sqlite3.connect(DATABASE_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.close()


_init_sqlite()


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@app.get("/")
def health():
    return jsonify({"service": "fraud-database-service", "status": "running"})


# ============================================================
# ALERT RULES
# ============================================================

@app.post("/rules")
def create_rule():
    data = request.get_json()

    required_fields = ["rule_name", "rule_type", "threshold_value", "severity"]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    cursor = conn.execute(
        """
        INSERT INTO alert_rules (
            rule_name, rule_type, threshold_value, threshold_secondary,
            severity, enabled, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["rule_name"],
            data["rule_type"],
            data["threshold_value"],
            data.get("threshold_secondary"),
            data["severity"],
            1 if data.get("enabled", 1) else 0,
            data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()

    return jsonify({"rule_id": rule_id, "message": "Rule created"}), 201


@app.get("/rules")
def get_rules():
    conn = get_db_connection()

    conditions = []
    params = []

    rule_type = request.args.get("rule_type")
    if rule_type:
        conditions.append("LOWER(rule_type) = LOWER(?)")
        params.append(rule_type)

    enabled = request.args.get("enabled")
    if enabled is not None and enabled != "":
        conditions.append("enabled = ?")
        params.append(1 if enabled.lower() in ("1", "true") else 0)

    query = """
        SELECT rule_id, rule_name, rule_type, threshold_value, threshold_secondary,
               severity, enabled, created_at
        FROM alert_rules
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY rule_id"

    rules = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in rules])


@app.get("/rules/<int:rule_id>")
def get_rule(rule_id):
    conn = get_db_connection()

    rule = conn.execute(
        """
        SELECT rule_id, rule_name, rule_type, threshold_value, threshold_secondary,
               severity, enabled, created_at
        FROM alert_rules
        WHERE rule_id = ?
        """,
        (rule_id,),
    ).fetchone()

    conn.close()

    if rule is None:
        return jsonify({"error": "Rule not found"}), 404

    return jsonify(dict(rule))


@app.put("/rules/<int:rule_id>")
def update_rule(rule_id):
    data = request.get_json()

    conn = get_db_connection()

    rule = conn.execute("SELECT * FROM alert_rules WHERE rule_id = ?", (rule_id,)).fetchone()

    if rule is None:
        conn.close()
        return jsonify({"error": "Rule not found"}), 404

    enabled = data.get("enabled", rule["enabled"])
    if isinstance(enabled, bool):
        enabled = 1 if enabled else 0

    conn.execute(
        """
        UPDATE alert_rules
        SET rule_name = ?,
            rule_type = ?,
            threshold_value = ?,
            threshold_secondary = ?,
            severity = ?,
            enabled = ?
        WHERE rule_id = ?
        """,
        (
            data.get("rule_name", rule["rule_name"]),
            data.get("rule_type", rule["rule_type"]),
            data.get("threshold_value", rule["threshold_value"]),
            data.get("threshold_secondary", rule["threshold_secondary"]),
            data.get("severity", rule["severity"]),
            enabled,
            rule_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Rule updated"})


@app.delete("/rules/<int:rule_id>")
def delete_rule(rule_id):
    conn = get_db_connection()

    cursor = conn.execute("DELETE FROM alert_rules WHERE rule_id = ?", (rule_id,))

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Rule not found"}), 404

    return jsonify({"message": "Rule deleted"})


# ============================================================
# ALERTS
# ============================================================

@app.post("/alerts")
def create_alert():
    data = request.get_json()

    required_fields = [
        "rule_id", "customer_id", "transaction_id", "transaction_amount", "severity", "status",
    ]
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    rule = conn.execute(
        "SELECT rule_id FROM alert_rules WHERE rule_id = ?", (data["rule_id"],)
    ).fetchone()
    if rule is None:
        conn.close()
        return jsonify({"error": "Rule not found"}), 404

    try:
        cursor = conn.execute(
            """
            INSERT INTO alerts (
                rule_id, customer_id, transaction_id, transaction_amount,
                transaction_recipient, transaction_datetime, transaction_category,
                severity, status, ai_explanation, explanation_generated_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["rule_id"],
                data["customer_id"],
                data["transaction_id"],
                data["transaction_amount"],
                data.get("transaction_recipient"),
                data.get("transaction_datetime"),
                data.get("transaction_category"),
                data["severity"],
                data.get("status", "new"),
                data.get("ai_explanation"),
                data.get("explanation_generated_at"),
                data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            ),
        )
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "Alert already exists for this rule and transaction", "duplicate": True}), 409

    conn.commit()
    alert_id = cursor.lastrowid
    conn.close()

    return jsonify({"alert_id": alert_id, "message": "Alert created"}), 201


@app.get("/alerts")
def get_alerts():
    conn = get_db_connection()

    conditions = []
    params = []

    status = request.args.get("status")
    if status:
        conditions.append("LOWER(status) = LOWER(?)")
        params.append(status)

    rule_id = request.args.get("rule_id")
    if rule_id:
        conditions.append("rule_id = ?")
        params.append(rule_id)

    customer_id = request.args.get("customer_id")
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)

    min_amount = request.args.get("min_amount")
    if min_amount:
        conditions.append("transaction_amount >= ?")
        params.append(min_amount)

    max_amount = request.args.get("max_amount")
    if max_amount:
        conditions.append("transaction_amount <= ?")
        params.append(max_amount)

    date_from = request.args.get("date_from")
    if date_from:
        conditions.append("DATE(transaction_datetime) >= DATE(?)")
        params.append(date_from)

    date_to = request.args.get("date_to")
    if date_to:
        conditions.append("DATE(transaction_datetime) <= DATE(?)")
        params.append(date_to)

    q = request.args.get("q")
    if q:
        conditions.append("(transaction_recipient LIKE ? OR transaction_category LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    query = """
        SELECT alert_id, rule_id, customer_id, transaction_id, transaction_amount,
               transaction_recipient, transaction_datetime, transaction_category,
               severity, status, ai_explanation, explanation_generated_at, created_at
        FROM alerts
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY alert_id DESC"

    alerts = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in alerts])


@app.get("/alerts/<int:alert_id>")
def get_alert(alert_id):
    conn = get_db_connection()

    alert = conn.execute(
        """
        SELECT alert_id, rule_id, customer_id, transaction_id, transaction_amount,
               transaction_recipient, transaction_datetime, transaction_category,
               severity, status, ai_explanation, explanation_generated_at, created_at
        FROM alerts
        WHERE alert_id = ?
        """,
        (alert_id,),
    ).fetchone()

    conn.close()

    if alert is None:
        return jsonify({"error": "Alert not found"}), 404

    return jsonify(dict(alert))


@app.put("/alerts/<int:alert_id>")
def update_alert(alert_id):
    data = request.get_json()

    conn = get_db_connection()

    alert = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()

    if alert is None:
        conn.close()
        return jsonify({"error": "Alert not found"}), 404

    conn.execute(
        """
        UPDATE alerts
        SET status = ?,
            ai_explanation = ?,
            explanation_generated_at = ?
        WHERE alert_id = ?
        """,
        (
            data.get("status", alert["status"]),
            data.get("ai_explanation", alert["ai_explanation"]),
            data.get("explanation_generated_at", alert["explanation_generated_at"]),
            alert_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Alert updated"})


@app.delete("/alerts/<int:alert_id>")
def delete_alert(alert_id):
    conn = get_db_connection()

    cursor = conn.execute("DELETE FROM alerts WHERE alert_id = ?", (alert_id,))

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Alert not found"}), 404

    return jsonify({"message": "Alert deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5013, debug=False, threaded=True)
