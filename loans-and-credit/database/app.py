import os

from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

DATABASE_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "loans_and_credit.db")


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
    return conn


@app.get("/")
def health():
    return jsonify({"service": "database-service", "status": "running"})


# ============================================================
# LOANS - CREATE
# ============================================================

@app.post("/loans")
def create_loan():
    data = request.get_json()

    required_fields = [
        "customer_id",
        "loan_type",
        "requested_amount",
        "loan_purpose",
        "application_date",
        "status",
        "interest_rate"
    ]

    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    cursor = conn.execute(
        """
        INSERT INTO loan_applications (
            customer_id,
            loan_type,
            requested_amount,
            loan_purpose,
            application_date,
            status,
            interest_rate,
            approved_amount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["customer_id"],
            data["loan_type"],
            data["requested_amount"],
            data["loan_purpose"],
            data["application_date"],
            data["status"],
            data["interest_rate"],
            data.get("approved_amount")
        ),
    )

    conn.commit()

    loan_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "loan_id": loan_id,
        "message": "Loan created"
    }), 201


# ============================================================
# LOANS - READ
# ============================================================

@app.get("/loans")
def get_loans():
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

    loan_type = request.args.get("loan_type")
    if loan_type:
        conditions.append("LOWER(loan_type) = LOWER(?)")
        params.append(loan_type)

    min_amount = request.args.get("min_amount")
    if min_amount:
        conditions.append("requested_amount >= ?")
        params.append(min_amount)

    max_amount = request.args.get("max_amount")
    if max_amount:
        conditions.append("requested_amount <= ?")
        params.append(max_amount)

    date_from = request.args.get("date_from")
    if date_from:
        conditions.append("application_date >= ?")
        params.append(date_from)

    date_to = request.args.get("date_to")
    if date_to:
        conditions.append("application_date <= ?")
        params.append(date_to)

    q = request.args.get("q")
    if q:
        conditions.append("(loan_purpose LIKE ? OR loan_type LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    query = """
        SELECT loan_id, customer_id, loan_type, requested_amount,
               loan_purpose, application_date, status,
               interest_rate, approved_amount
        FROM loan_applications
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    loans = conn.execute(query, params).fetchall()

    conn.close()

    return jsonify([dict(row) for row in loans])


@app.get("/loans/<int:loan_id>")
def get_loan(loan_id):
    conn = get_db_connection()

    loan = conn.execute(
        """
        SELECT loan_id, customer_id, loan_type, requested_amount,
               loan_purpose, application_date, status,
               interest_rate, approved_amount
        FROM loan_applications
        WHERE loan_id = ?
        """,
        (loan_id,),
    ).fetchone()

    conn.close()

    if loan is None:
        return jsonify({"error": "Loan not found"}), 404

    return jsonify(dict(loan))


@app.get("/loans/by-customer")
def get_loans_by_customer():
    customer_id = request.args.get("customer_id", "").strip()

    if not customer_id:
        return jsonify({"error": "customer_id required"}), 400

    conn = get_db_connection()

    loans = conn.execute(
        """
        SELECT loan_id, customer_id, loan_type, requested_amount,
               loan_purpose, application_date, status,
               interest_rate, approved_amount
        FROM loan_applications
        WHERE customer_id = ?
        """,
        (customer_id,),
    ).fetchall()

    conn.close()

    if not loans:
        return jsonify({"error": "No loans found"}), 404

    return jsonify([dict(row) for row in loans])


# ============================================================
# LOANS - UPDATE
# ============================================================

@app.put("/loans/<int:loan_id>")
def update_loan(loan_id):
    data = request.get_json()

    conn = get_db_connection()

    loan = conn.execute(
        """
        SELECT *
        FROM loan_applications
        WHERE loan_id = ?
        """,
        (loan_id,),
    ).fetchone()

    if loan is None:
        conn.close()
        return jsonify({"error": "Loan not found"}), 404

    conn.execute(
        """
        UPDATE loan_applications
        SET customer_id = ?,
            loan_type = ?,
            requested_amount = ?,
            loan_purpose = ?,
            application_date = ?,
            status = ?,
            interest_rate = ?,
            approved_amount = ?
        WHERE loan_id = ?
        """,
        (
            data.get("customer_id", loan["customer_id"]),
            data.get("loan_type", loan["loan_type"]),
            data.get("requested_amount", loan["requested_amount"]),
            data.get("loan_purpose", loan["loan_purpose"]),
            data.get("application_date", loan["application_date"]),
            data.get("status", loan["status"]),
            data.get("interest_rate", loan["interest_rate"]),
            data.get("approved_amount", loan["approved_amount"]),
            loan_id
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Loan updated"
    })


# ============================================================
# LOANS - DELETE
# ============================================================

@app.delete("/loans/<int:loan_id>")
def delete_loan(loan_id):
    conn = get_db_connection()

    cursor = conn.execute(
        """
        DELETE FROM loan_applications
        WHERE loan_id = ?
        """,
        (loan_id,),
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Loan not found"}), 404

    return jsonify({
        "message": "Loan deleted"
    })


# ============================================================
# REPAYMENTS - CREATE
# ============================================================

@app.post("/repayments")
def create_repayment():
    data = request.get_json()

    required_fields = [
        "loan_id",
        "due_date",
        "payment_amount",
        "principal_amount",
        "interest_amount",
        "payment_status"
    ]

    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    # Check that the loan exists
    loan = conn.execute(
        """
        SELECT loan_id
        FROM loan_applications
        WHERE loan_id = ?
        """,
        (data["loan_id"],),
    ).fetchone()

    if loan is None:
        conn.close()
        return jsonify({"error": "Loan not found"}), 404

    cursor = conn.execute(
        """
        INSERT INTO repayments (
            loan_id,
            due_date,
            payment_amount,
            principal_amount,
            interest_amount,
            amount_paid,
            payment_date,
            payment_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["loan_id"],
            data["due_date"],
            data["payment_amount"],
            data["principal_amount"],
            data["interest_amount"],
            data.get("amount_paid", 0),
            data.get("payment_date"),
            data["payment_status"]
        ),
    )

    conn.commit()

    repayment_id = cursor.lastrowid

    conn.close()

    return jsonify({
        "repayment_id": repayment_id,
        "message": "Repayment created"
    }), 201


# ============================================================
# REPAYMENTS - READ
# ============================================================

@app.get("/repayments")
def get_repayments():
    conn = get_db_connection()

    conditions = []
    params = []

    loan_id = request.args.get("loan_id")
    if loan_id:
        conditions.append("loan_id = ?")
        params.append(loan_id)

    payment_status = request.args.get("payment_status")
    if payment_status:
        conditions.append("LOWER(payment_status) = LOWER(?)")
        params.append(payment_status)

    due_before = request.args.get("due_before")
    if due_before:
        conditions.append("due_date <= ?")
        params.append(due_before)

    due_after = request.args.get("due_after")
    if due_after:
        conditions.append("due_date >= ?")
        params.append(due_after)

    overdue = request.args.get("overdue")
    if overdue and overdue.lower() == "true":
        conditions.append("due_date < date('now') AND LOWER(payment_status) != 'paid'")
        conditions.append("(amount_paid IS NULL OR amount_paid < payment_amount)")

    unpaid = request.args.get("unpaid")
    if unpaid and unpaid.lower() == "true":
        conditions.append("LOWER(payment_status) != 'paid'")

    query = """
        SELECT repayment_id, loan_id, due_date, payment_amount,
               principal_amount, interest_amount, amount_paid,
               payment_date, payment_status
        FROM repayments
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    repayments = conn.execute(query, params).fetchall()

    conn.close()

    return jsonify([dict(row) for row in repayments])


@app.get("/repayments/<int:repayment_id>")
def get_repayment(repayment_id):
    conn = get_db_connection()

    repayment = conn.execute(
        """
        SELECT repayment_id, loan_id, due_date, payment_amount,
               principal_amount, interest_amount, amount_paid,
               payment_date, payment_status
        FROM repayments
        WHERE repayment_id = ?
        """,
        (repayment_id,),
    ).fetchone()

    conn.close()

    if repayment is None:
        return jsonify({"error": "Repayment not found"}), 404

    return jsonify(dict(repayment))


@app.get("/repayments/by-loan")
def get_repayments_by_loan():
    loan_id = request.args.get("loan_id", "").strip()

    if not loan_id:
        return jsonify({"error": "loan_id required"}), 400

    conn = get_db_connection()

    repayments = conn.execute(
        """
        SELECT repayment_id, loan_id, due_date, payment_amount,
               principal_amount, interest_amount, amount_paid,
               payment_date, payment_status
        FROM repayments
        WHERE loan_id = ?
        """,
        (loan_id,),
    ).fetchall()

    conn.close()

    if not repayments:
        return jsonify({"error": "No repayments found"}), 404

    return jsonify([dict(row) for row in repayments])


@app.get("/repayments/by-status")
def get_repayments_by_status():
    payment_status = request.args.get("payment_status", "").strip()

    if not payment_status:
        return jsonify({"error": "payment_status required"}), 400

    conn = get_db_connection()

    repayments = conn.execute(
        """
        SELECT repayment_id, loan_id, due_date, payment_amount,
               principal_amount, interest_amount, amount_paid,
               payment_date, payment_status
        FROM repayments
        WHERE payment_status = ?
        """,
        (payment_status,),
    ).fetchall()

    conn.close()

    if not repayments:
        return jsonify({"error": "No repayments found"}), 404

    return jsonify([dict(row) for row in repayments])


# ============================================================
# REPAYMENTS - UPDATE
# ============================================================

@app.put("/repayments/<int:repayment_id>")
def update_repayment(repayment_id):
    data = request.get_json()

    conn = get_db_connection()

    repayment = conn.execute(
        """
        SELECT *
        FROM repayments
        WHERE repayment_id = ?
        """,
        (repayment_id,),
    ).fetchone()

    if repayment is None:
        conn.close()
        return jsonify({"error": "Repayment not found"}), 404

    conn.execute(
        """
        UPDATE repayments
        SET loan_id = ?,
            due_date = ?,
            payment_amount = ?,
            principal_amount = ?,
            interest_amount = ?,
            amount_paid = ?,
            payment_date = ?,
            payment_status = ?
        WHERE repayment_id = ?
        """,
        (
            data.get("loan_id", repayment["loan_id"]),
            data.get("due_date", repayment["due_date"]),
            data.get("payment_amount", repayment["payment_amount"]),
            data.get("principal_amount", repayment["principal_amount"]),
            data.get("interest_amount", repayment["interest_amount"]),
            data.get("amount_paid", repayment["amount_paid"]),
            data.get("payment_date", repayment["payment_date"]),
            data.get("payment_status", repayment["payment_status"]),
            repayment_id
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Repayment updated"
    })


# ============================================================
# REPAYMENTS - DELETE
# ============================================================

@app.delete("/repayments/<int:repayment_id>")
def delete_repayment(repayment_id):
    conn = get_db_connection()

    cursor = conn.execute(
        """
        DELETE FROM repayments
        WHERE repayment_id = ?
        """,
        (repayment_id,),
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Repayment not found"}), 404

    return jsonify({
        "message": "Repayment deleted"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5012, debug=False, threaded=True)