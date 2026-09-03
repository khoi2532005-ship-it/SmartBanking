import os

from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)


@app.errorhandler(Exception)
def handle_exception(exc):
    app.logger.exception(exc)
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


DATABASE_NAME = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "budgeting_and_insights.db"
)


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
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@app.get("/")
def health():
    return jsonify({"service": "budgets-database-service", "status": "running"})


# ============================================================
# BUDGETS - CREATE
# ============================================================

@app.post("/budgets")
def create_budget():
    data = request.get_json(silent=True) or {}

    required_fields = ["customer_id", "category", "monthly_limit", "month", "year"]

    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    try:
        cursor = conn.execute(
            """
            INSERT INTO budgets (
                customer_id,
                category,
                monthly_limit,
                month,
                year,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                data["customer_id"],
                data["category"],
                data["monthly_limit"],
                data["month"],
                data["year"],
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return (
            jsonify(
                {
                    "error": "A budget for that customer, category, month and year "
                    "already exists"
                }
            ),
            409,
        )

    budget_id = cursor.lastrowid

    conn.close()

    return jsonify({"budget_id": budget_id, "message": "Budget created"}), 201


# ============================================================
# BUDGETS - READ
# ============================================================

@app.get("/budgets")
def get_budgets():
    conn = get_db_connection()

    conditions = []
    params = []

    for field in ("customer_id", "category", "month", "year"):
        value = request.args.get(field)
        if value not in (None, ""):
            conditions.append(f"{field} = ?")
            params.append(value)

    query = "SELECT * FROM budgets"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY year DESC, month DESC, category ASC"

    rows = conn.execute(query, params).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.get("/budgets/<int:budget_id>")
def get_budget(budget_id):
    conn = get_db_connection()

    row = conn.execute(
        "SELECT * FROM budgets WHERE budget_id = ?", (budget_id,)
    ).fetchone()

    conn.close()

    if row is None:
        return jsonify({"error": "Budget not found"}), 404

    return jsonify(dict(row))


# ============================================================
# BUDGETS - UPDATE
# ============================================================

@app.put("/budgets/<int:budget_id>")
def update_budget(budget_id):
    data = request.get_json(silent=True) or {}

    conn = get_db_connection()

    budget = conn.execute(
        "SELECT * FROM budgets WHERE budget_id = ?", (budget_id,)
    ).fetchone()

    if budget is None:
        conn.close()
        return jsonify({"error": "Budget not found"}), 404

    conn.execute(
        """
        UPDATE budgets
        SET customer_id = ?,
            category = ?,
            monthly_limit = ?,
            month = ?,
            year = ?
        WHERE budget_id = ?
        """,
        (
            data.get("customer_id", budget["customer_id"]),
            data.get("category", budget["category"]),
            data.get("monthly_limit", budget["monthly_limit"]),
            data.get("month", budget["month"]),
            data.get("year", budget["year"]),
            budget_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Budget updated"})


# ============================================================
# BUDGETS - DELETE
# ============================================================

@app.delete("/budgets/<int:budget_id>")
def delete_budget(budget_id):
    conn = get_db_connection()

    cursor = conn.execute("DELETE FROM budgets WHERE budget_id = ?", (budget_id,))

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Budget not found"}), 404

    return jsonify({"message": "Budget deleted"})


# ============================================================
# CATEGORIES
# ============================================================

@app.post("/categories")
def create_category():
    data = request.get_json(silent=True) or {}

    for field in ("name", "description"):
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    try:
        cursor = conn.execute(
            "INSERT INTO categories (name, description) VALUES (?, ?)",
            (data["name"], data["description"]),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "A category with that name already exists"}), 409

    category_id = cursor.lastrowid

    conn.close()

    return jsonify({"category_id": category_id, "message": "Category created"}), 201


@app.get("/categories")
def get_categories():
    conn = get_db_connection()

    rows = conn.execute("SELECT * FROM categories ORDER BY name ASC").fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.get("/categories/<int:category_id>")
def get_category(category_id):
    conn = get_db_connection()

    row = conn.execute(
        "SELECT * FROM categories WHERE category_id = ?", (category_id,)
    ).fetchone()

    conn.close()

    if row is None:
        return jsonify({"error": "Category not found"}), 404

    return jsonify(dict(row))


@app.put("/categories/<int:category_id>")
def update_category(category_id):
    data = request.get_json(silent=True) or {}

    conn = get_db_connection()

    category = conn.execute(
        "SELECT * FROM categories WHERE category_id = ?", (category_id,)
    ).fetchone()

    if category is None:
        conn.close()
        return jsonify({"error": "Category not found"}), 404

    conn.execute(
        "UPDATE categories SET name = ?, description = ? WHERE category_id = ?",
        (
            data.get("name", category["name"]),
            data.get("description", category["description"]),
            category_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify({"message": "Category updated"})


@app.delete("/categories/<int:category_id>")
def delete_category(category_id):
    conn = get_db_connection()

    cursor = conn.execute(
        "DELETE FROM categories WHERE category_id = ?", (category_id,)
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Category not found"}), 404

    return jsonify({"message": "Category deleted"})


# ============================================================
# BUDGET INSIGHTS
# ============================================================

@app.post("/insights")
def create_insight():
    data = request.get_json(silent=True) or {}

    for field in ("budget_id", "insight_text", "model_used"):
        if field not in data:
            return jsonify({"error": f"{field} required"}), 400

    conn = get_db_connection()

    budget = conn.execute(
        "SELECT budget_id FROM budgets WHERE budget_id = ?", (data["budget_id"],)
    ).fetchone()

    if budget is None:
        conn.close()
        return jsonify({"error": "Budget not found"}), 404

    cursor = conn.execute(
        """
        INSERT INTO budget_insights (
            budget_id,
            insight_text,
            generated_at,
            model_used
        )
        VALUES (?, ?, datetime('now'), ?)
        """,
        (data["budget_id"], data["insight_text"], data["model_used"]),
    )

    conn.commit()

    insight_id = cursor.lastrowid

    conn.close()

    return jsonify({"insight_id": insight_id, "message": "Insight created"}), 201


@app.get("/insights")
def get_insights():
    conn = get_db_connection()

    conditions = []
    params = []

    budget_id = request.args.get("budget_id")
    if budget_id not in (None, ""):
        conditions.append("i.budget_id = ?")
        params.append(budget_id)

    customer_id = request.args.get("customer_id")
    if customer_id not in (None, ""):
        conditions.append("b.customer_id = ?")
        params.append(customer_id)

    query = """
        SELECT i.*, b.customer_id, b.category, b.month, b.year
        FROM budget_insights i
        JOIN budgets b ON b.budget_id = i.budget_id
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY i.generated_at DESC"

    limit = request.args.get("limit")
    if limit not in (None, ""):
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


@app.get("/insights/<int:insight_id>")
def get_insight(insight_id):
    conn = get_db_connection()

    row = conn.execute(
        "SELECT * FROM budget_insights WHERE insight_id = ?", (insight_id,)
    ).fetchone()

    conn.close()

    if row is None:
        return jsonify({"error": "Insight not found"}), 404

    return jsonify(dict(row))


@app.delete("/insights/<int:insight_id>")
def delete_insight(insight_id):
    conn = get_db_connection()

    cursor = conn.execute(
        "DELETE FROM budget_insights WHERE insight_id = ?", (insight_id,)
    )

    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        return jsonify({"error": "Insight not found"}), 404

    return jsonify({"message": "Insight deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5014, debug=False, threaded=True)
