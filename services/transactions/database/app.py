import os
import sqlite3

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


DATABASE_NAME = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "transactions.db"
)


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


@app.get("/customers")
def get_customers():
    conn = get_db_connection()
    customers = conn.execute(
        "SELECT customer_id, first_name, last_name, email, phone, date_of_birth, address FROM customers"
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in customers])


@app.get("/accounts")
def get_accounts():
    conn = get_db_connection()
    accounts = conn.execute(
        "SELECT account_id, customer_id, account_number, account_type, balance, currency, status FROM accounts"
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in accounts])


@app.post("/transactions")
def create_transaction():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    required_fields = ["account_id", "amount", "currency", "type", "date"]
    for field in required_fields:
        if field not in data or data.get(field) in (None, ""):
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()
    account = conn.execute(
        "SELECT account_id FROM accounts WHERE account_id = ?",
        (data["account_id"],),
    ).fetchone()
    if account is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404

    cursor = conn.execute(
        """
        INSERT INTO transactions (
            account_id, amount, currency, type, category, description, date
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["account_id"],
            data["amount"],
            data["currency"],
            data["type"],
            data.get("category"),
            data.get("description"),
            data["date"],
        ),
    )
    conn.commit()
    transaction_id = cursor.lastrowid
    conn.close()

    return jsonify({"transaction_id": transaction_id, "message": "Transaction created"}), 201


@app.get("/transactions")
def get_transactions():
    conn = get_db_connection()

    conditions = []
    params = []

    account_id = request.args.get("account_id")
    if account_id:
        conditions.append("t.account_id = ?")
        params.append(account_id)

    customer_id = request.args.get("customer_id")
    if customer_id:
        conditions.append("a.customer_id = ?")
        params.append(customer_id)

    ttype = request.args.get("type")
    if ttype:
        conditions.append("LOWER(t.type) = LOWER(?)")
        params.append(ttype)

    category = request.args.get("category")
    if category:
        conditions.append("LOWER(t.category) = LOWER(?)")
        params.append(category)

    min_amount = request.args.get("min_amount")
    if min_amount:
        conditions.append("t.amount >= ?")
        params.append(min_amount)

    max_amount = request.args.get("max_amount")
    if max_amount:
        conditions.append("t.amount <= ?")
        params.append(max_amount)

    date_from = request.args.get("date_from")
    if date_from:
        conditions.append("t.date >= ?")
        params.append(date_from)

    date_to = request.args.get("date_to")
    if date_to:
        conditions.append("t.date <= ?")
        params.append(date_to)

    q = request.args.get("q")
    if q:
        conditions.append("(t.description LIKE ? OR t.category LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    query = """
        SELECT t.transaction_id, t.account_id, t.amount, t.currency, t.type, t.category, t.description, t.date,
               a.customer_id
        FROM transactions t
        LEFT JOIN accounts a ON a.account_id = t.account_id
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    txs = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(row) for row in txs])


@app.get("/transactions/<int:transaction_id>")
def get_transaction(transaction_id):
    conn = get_db_connection()
    tx = conn.execute(
        """
        SELECT transaction_id, account_id, amount, currency, type, category, description, date
        FROM transactions
        WHERE transaction_id = ?
        """,
        (transaction_id,),
    ).fetchone()
    conn.close()

    if tx is None:
        return jsonify({"error": "Transaction not found"}), 404

    return jsonify(dict(tx))


@app.put("/transactions/<int:transaction_id>")
def update_transaction(transaction_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400

    conn = get_db_connection()
    tx = conn.execute(
        "SELECT * FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    if tx is None:
        conn.close()
        return jsonify({"error": "Transaction not found"}), 404

    conn.execute(
        """
        UPDATE transactions
        SET account_id = ?,
            amount = ?,
            currency = ?,
            type = ?,
            category = ?,
            description = ?,
            date = ?
        WHERE transaction_id = ?
        """,
        (
            data.get("account_id", tx["account_id"]),
            data.get("amount", tx["amount"]),
            data.get("currency", tx["currency"]),
            data.get("type", tx["type"]),
            data.get("category", tx["category"]),
            data.get("description", tx["description"]),
            data.get("date", tx["date"]),
            transaction_id,
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Transaction updated"})


@app.delete("/transactions/<int:transaction_id>")
def delete_transaction(transaction_id):
    conn = get_db_connection()
    cursor = conn.execute(
        "DELETE FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    )
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Transaction not found"}), 404

    return jsonify({"message": "Transaction deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5015, debug=False, threaded=True)
