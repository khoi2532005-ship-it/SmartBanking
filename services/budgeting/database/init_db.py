import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "budgeting_and_insights.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute("PRAGMA foreign_keys = ON")

# ============================================================
# CATEGORIES
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL
    )
""")

cursor.execute("DELETE FROM categories")

categories = [
    (1, "Groceries", "Supermarkets, food markets and grocery delivery"),
    (2, "Dining Out", "Restaurants, cafes, takeaway and food delivery"),
    (3, "Transport", "Public transport, fuel, tolls and rideshare"),
    (4, "Entertainment", "Cinema, events, games and hobbies"),
    (5, "Utilities", "Electricity, gas, water and internet bills"),
    (6, "Shopping", "Clothing, electronics and general retail"),
    (7, "Health", "Pharmacy, medical appointments and fitness"),
    (8, "Subscriptions", "Streaming services and recurring memberships"),
    (9, "Education", "Course fees, textbooks and learning materials"),
    (10, "Savings", "Transfers into savings and investment accounts"),
]

cursor.executemany("""
    INSERT INTO categories (category_id, name, description)
    VALUES (?, ?, ?)
""", categories)

# ============================================================
# BUDGETS
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS budgets (
        budget_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        monthly_limit REAL NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        created_at TEXT NOT NULL,

        UNIQUE (customer_id, category, month, year)
    )
""")

cursor.execute("DELETE FROM budgets")

budgets = [
    # Customer 1 - current month (September 2026)
    (1, 1, "Groceries", 800.00, 9, 2026, "2026-09-01 08:15:00"),
    (2, 1, "Dining Out", 300.00, 9, 2026, "2026-09-01 08:16:00"),
    (3, 1, "Transport", 200.00, 9, 2026, "2026-09-01 08:17:00"),
    (4, 1, "Entertainment", 150.00, 9, 2026, "2026-09-01 08:18:00"),
    (5, 1, "Utilities", 250.00, 9, 2026, "2026-09-01 08:19:00"),
    (6, 1, "Shopping", 400.00, 9, 2026, "2026-09-01 08:20:00"),
    (7, 1, "Subscriptions", 60.00, 9, 2026, "2026-09-01 08:21:00"),
    # Customer 1 - previous month (August 2026), gives the AI some history
    (8, 1, "Groceries", 750.00, 8, 2026, "2026-08-01 09:02:00"),
    (9, 1, "Dining Out", 250.00, 8, 2026, "2026-08-01 09:03:00"),
    (10, 1, "Transport", 200.00, 8, 2026, "2026-08-01 09:04:00"),
    # Customer 2 - current month
    (11, 2, "Groceries", 500.00, 9, 2026, "2026-09-02 17:45:00"),
    (12, 2, "Dining Out", 220.00, 9, 2026, "2026-09-02 17:46:00"),
    (13, 2, "Health", 180.00, 9, 2026, "2026-09-02 17:47:00"),
    (14, 2, "Education", 350.00, 9, 2026, "2026-09-02 17:48:00"),
]

cursor.executemany("""
    INSERT INTO budgets (
        budget_id,
        customer_id,
        category,
        monthly_limit,
        month,
        year,
        created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", budgets)

# ============================================================
# BUDGET INSIGHTS
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS budget_insights (
        insight_id INTEGER PRIMARY KEY AUTOINCREMENT,
        budget_id INTEGER NOT NULL,
        insight_text TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        model_used TEXT NOT NULL,

        FOREIGN KEY (budget_id)
            REFERENCES budgets(budget_id)
            ON DELETE CASCADE
    )
""")

cursor.execute("DELETE FROM budget_insights")

insights = [
    (1, 2, "You have spent $412 of your $300 Dining Out budget, putting you 37% over "
        "with most of the month still to run. Cutting back to two takeaway meals a week "
        "would bring you close to your limit.",
        "2026-09-02 19:30:00", "qwen2.5:0.5b"),
    (2, 3, "Transport is $18 over its $200 limit. The overspend is small and driven by "
        "rideshare trips rather than fuel, so switching two trips to public transport "
        "would recover the difference.",
        "2026-09-02 19:31:00", "qwen2.5:0.5b"),
    (3, 6, "Shopping is tracking at $505 against a $400 limit. This is your largest "
        "overspend this month and it is concentrated in electronics.",
        "2026-09-02 19:32:00", "qwen2.5:0.5b"),
    (4, 1, "Groceries are on track at $645 of $800 with a week remaining. You should "
        "finish the month roughly $80 under budget.",
        "2026-09-02 19:33:00", "qwen2.5:0.5b"),
    (5, 4, "Entertainment spending is well controlled at $90 of $150. There is headroom "
        "here that could offset the Dining Out overspend.",
        "2026-09-02 19:34:00", "qwen2.5:0.5b"),
    (6, 5, "Utilities came in at $240 against a $250 limit, effectively on budget. "
        "This category is stable month to month and needs no adjustment.",
        "2026-09-02 19:35:00", "qwen2.5:0.5b"),
    (7, 9, "Last month Dining Out finished at $268 against a $250 limit. The same "
        "pattern is repeating in September, so consider raising the limit to $300 "
        "or planning fewer restaurant meals.",
        "2026-08-31 21:10:00", "llama3.1:8b"),
    (8, 8, "August groceries finished at $712 of $750, just under budget. Your "
        "September limit of $800 gives you a little more room than you used.",
        "2026-08-31 21:11:00", "llama3.1:8b"),
    (9, 11, "Groceries are at $268 of $500 and pacing comfortably under budget for "
        "the month.",
        "2026-09-03 07:20:00", "qwen2.5:0.5b"),
    (10, 14, "Education spending of $350 has used the full budget in a single "
        "textbook purchase. Expect no further room in this category this month.",
        "2026-09-03 07:21:00", "qwen2.5:0.5b"),
]

cursor.executemany("""
    INSERT INTO budget_insights (
        insight_id,
        budget_id,
        insight_text,
        generated_at,
        model_used
    )
    VALUES (?, ?, ?, ?, ?)
""", insights)

conn.commit()

conn.close()

print(f"Database created successfully: {DATABASE_NAME}")
print(f"  categories: {len(categories)}")
print(f"  budgets: {len(budgets)}")
print(f"  budget_insights: {len(insights)}")
