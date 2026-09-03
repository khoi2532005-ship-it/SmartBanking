import os
import sqlite3

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


DATABASE_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "accounts_and_customers.db")


def _init_sqlite():
    conn = sqlite3.connect(DATABASE_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()


_init_sqlite()


def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@app.get("/")
def health():
    return jsonify({"service": "database-service", "status": "running"})


CUSTOMER_COLUMNS = (
    "customer_id, first_name, last_name, email, phone, date_of_birth, "
    "address, created_at, updated_at"
)

ACCOUNT_COLUMNS = (
    "account_id, customer_id, account_number, account_type, balance, "
    "currency, status, created_at, updated_at"
)

SUMMARY_COLUMNS = "summary_id, customer_id, summary_type, summary_text, risk_level, created_at"


# ============================================================
# CUSTOMERS - CREATE
# ============================================================

@app.post("/customers")
def create_customer():
    data = request.get_json()

    required_fields = ["first_name", "last_name", "email"]
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    existing = conn.execute(
        "SELECT customer_id FROM customers WHERE LOWER(email) = LOWER(?)",
        (data["email"],),
    ).fetchone()
    if existing is not None:
        conn.close()
        return jsonify({"error": "A customer with this email already exists"}), 409

    cursor = conn.execute(
        """
        INSERT INTO customers (
            first_name, last_name, email, phone, date_of_birth, address
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data["first_name"],
            data["last_name"],
            data["email"],
            data.get("phone"),
            data.get("date_of_birth"),
            data.get("address"),
        ),
    )

    conn.commit()
    customer_id = cursor.lastrowid
    conn.close()

    return jsonify({"customer_id": customer_id, "message": "Customer created"}), 201


# ============================================================
# CUSTOMERS - READ
# ============================================================

@app.get("/customers")
def get_customers():
    conn = get_db_connection()

    conditions = []
    params = []

    q = request.args.get("q")
    if q:
        conditions.append(
            "(first_name LIKE ? OR last_name LIKE ? OR email LIKE ? OR phone LIKE ?)"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    email = request.args.get("email")
    if email:
        conditions.append("LOWER(email) = LOWER(?)")
        params.append(email)

    query = f"SELECT {CUSTOMER_COLUMNS} FROM customers"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY customer_id"

    customers = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in customers])


@app.get("/customers/<int:customer_id>")
def get_customer(customer_id):
    conn = get_db_connection()

    customer = conn.execute(
        f"SELECT {CUSTOMER_COLUMNS} FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()

    conn.close()

    if customer is None:
        return jsonify({"error": "Customer not found"}), 404

    return jsonify(dict(customer))


# ============================================================
# CUSTOMERS - UPDATE
# ============================================================

@app.put("/customers/<int:customer_id>")
def update_customer(customer_id):
    data = request.get_json()

    conn = get_db_connection()

    customer = conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()

    if customer is None:
        conn.close()
        return jsonify({"error": "Customer not found"}), 404

    if "email" in data and data["email"]:
        clash = conn.execute(
            "SELECT customer_id FROM customers WHERE LOWER(email) = LOWER(?) AND customer_id != ?",
            (data["email"], customer_id),
        ).fetchone()
        if clash is not None:
            conn.close()
            return jsonify({"error": "A customer with this email already exists"}), 409

    conn.execute(
        """
        UPDATE customers
        SET first_name = ?,
            last_name = ?,
            email = ?,
            phone = ?,
            date_of_birth = ?,
            address = ?,
            updated_at = datetime('now')
        WHERE customer_id = ?
        """,
        (
            data.get("first_name", customer["first_name"]),
            data.get("last_name", customer["last_name"]),
            data.get("email", customer["email"]),
            data.get("phone", customer["phone"]),
            data.get("date_of_birth", customer["date_of_birth"]),
            data.get("address", customer["address"]),
            customer_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Customer updated"})


# ============================================================
# CUSTOMERS - DELETE
# ============================================================

@app.delete("/customers/<int:customer_id>")
def delete_customer(customer_id):
    conn = get_db_connection()

    cursor = conn.execute(
        "DELETE FROM customers WHERE customer_id = ?", (customer_id,)
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Customer not found"}), 404

    return jsonify({"message": "Customer deleted"})


# ============================================================
# ACCOUNTS - CREATE
# ============================================================

@app.post("/accounts")
def create_account():
    data = request.get_json()

    required_fields = ["customer_id", "account_number", "account_type"]
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    customer = conn.execute(
        "SELECT customer_id FROM customers WHERE customer_id = ?",
        (data["customer_id"],),
    ).fetchone()
    if customer is None:
        conn.close()
        return jsonify({"error": "Customer not found"}), 404

    clash = conn.execute(
        "SELECT account_id FROM accounts WHERE account_number = ?",
        (data["account_number"],),
    ).fetchone()
    if clash is not None:
        conn.close()
        return jsonify({"error": "An account with this account_number already exists"}), 409

    cursor = conn.execute(
        """
        INSERT INTO accounts (
            customer_id, account_number, account_type, balance, currency, status
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            data["customer_id"],
            data["account_number"],
            data["account_type"],
            data.get("balance", 0),
            data.get("currency", "AUD"),
            data.get("status", "ACTIVE"),
        ),
    )

    conn.commit()
    account_id = cursor.lastrowid
    conn.close()

    return jsonify({"account_id": account_id, "message": "Account created"}), 201


# ============================================================
# ACCOUNTS - READ
# ============================================================

@app.get("/accounts")
def get_accounts():
    conn = get_db_connection()

    conditions = []
    params = []

    customer_id = request.args.get("customer_id")
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)

    status = request.args.get("status")
    if status:
        conditions.append("LOWER(status) = LOWER(?)")
        params.append(status)

    account_type = request.args.get("account_type")
    if account_type:
        conditions.append("LOWER(account_type) = LOWER(?)")
        params.append(account_type)

    min_balance = request.args.get("min_balance")
    if min_balance:
        conditions.append("balance >= ?")
        params.append(min_balance)

    max_balance = request.args.get("max_balance")
    if max_balance:
        conditions.append("balance <= ?")
        params.append(max_balance)

    q = request.args.get("q")
    if q:
        conditions.append("(account_number LIKE ? OR account_type LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    query = f"SELECT {ACCOUNT_COLUMNS} FROM accounts"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY account_id"

    accounts = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in accounts])


@app.get("/accounts/<int:account_id>")
def get_account(account_id):
    conn = get_db_connection()

    account = conn.execute(
        f"SELECT {ACCOUNT_COLUMNS} FROM accounts WHERE account_id = ?",
        (account_id,),
    ).fetchone()

    conn.close()

    if account is None:
        return jsonify({"error": "Account not found"}), 404

    return jsonify(dict(account))


# ============================================================
# ACCOUNTS - UPDATE
# ============================================================

@app.put("/accounts/<int:account_id>")
def update_account(account_id):
    data = request.get_json()

    conn = get_db_connection()

    account = conn.execute(
        "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
    ).fetchone()

    if account is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404

    conn.execute(
        """
        UPDATE accounts
        SET account_type = ?,
            balance = ?,
            currency = ?,
            status = ?,
            updated_at = datetime('now')
        WHERE account_id = ?
        """,
        (
            data.get("account_type", account["account_type"]),
            data.get("balance", account["balance"]),
            data.get("currency", account["currency"]),
            data.get("status", account["status"]),
            account_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Account updated"})


# ============================================================
# ACCOUNTS - DELETE
# ============================================================

@app.delete("/accounts/<int:account_id>")
def delete_account(account_id):
    conn = get_db_connection()

    cursor = conn.execute(
        "DELETE FROM accounts WHERE account_id = ?", (account_id,)
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Account not found"}), 404

    return jsonify({"message": "Account deleted"})


# ============================================================
# AI SUMMARIES - CREATE / READ
# ============================================================

@app.post("/ai-summaries")
def create_ai_summary():
    data = request.get_json()

    required_fields = ["customer_id", "summary_type", "summary_text"]
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    customer = conn.execute(
        "SELECT customer_id FROM customers WHERE customer_id = ?",
        (data["customer_id"],),
    ).fetchone()
    if customer is None:
        conn.close()
        return jsonify({"error": "Customer not found"}), 404

    cursor = conn.execute(
        """
        INSERT INTO ai_summaries (
            customer_id, summary_type, summary_text, risk_level
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            data["customer_id"],
            data["summary_type"],
            data["summary_text"],
            data.get("risk_level"),
        ),
    )

    conn.commit()
    summary_id = cursor.lastrowid
    conn.close()

    return jsonify({"summary_id": summary_id, "message": "AI summary saved"}), 201


@app.get("/ai-summaries")
def get_ai_summaries():
    conn = get_db_connection()

    conditions = []
    params = []

    customer_id = request.args.get("customer_id")
    if customer_id:
        conditions.append("customer_id = ?")
        params.append(customer_id)

    summary_type = request.args.get("summary_type")
    if summary_type:
        conditions.append("LOWER(summary_type) = LOWER(?)")
        params.append(summary_type)

    query = f"SELECT {SUMMARY_COLUMNS} FROM ai_summaries"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY summary_id DESC"

    summaries = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in summaries])


@app.get("/ai-summaries/<int:summary_id>")
def get_ai_summary(summary_id):
    conn = get_db_connection()

    summary = conn.execute(
        f"SELECT {SUMMARY_COLUMNS} FROM ai_summaries WHERE summary_id = ?",
        (summary_id,),
    ).fetchone()

    conn.close()

    if summary is None:
        return jsonify({"error": "AI summary not found"}), 404

    return jsonify(dict(summary))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5011, debug=False, threaded=True)
