import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "transactions.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

# Transactions table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        type TEXT NOT NULL,
        category TEXT,
        description TEXT,
        date TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )
""")
cursor.execute("DELETE FROM transactions")
transactions = [
    (1, 1, 250.00, "AUD", "Deposit", "Salary", "Monthly salary", "2024-08-01", None),
    (2, 2, -50.25, "AUD", "Withdrawal", "Groceries", "Supermarket", "2024-08-02", None),
    (3, 3, -120.00, "AUD", "Transfer", "Rent", "August rent", "2024-08-03", None),
    (4, 5, 500.00, "AUD", "Deposit", "Income", "Refund", "2024-08-05", None),
    (5, 5, -80.00, "AUD", "Withdrawal", "Dining Out", "Dinner with team", "2024-08-06", None),
    (6, 2, -15.75, "AUD", "Withdrawal", "Dining Out", "Coffee shop", "2024-08-07", None),
    (7, 3, -60.00, "AUD", "Withdrawal", "Groceries", "Weekly groceries", "2024-08-08", None),
    (8, 1, -200.00, "AUD", "Transfer", "Utilities", "Electric bill", "2024-08-09", None),
    (9, 5, -30.00, "AUD", "Withdrawal", "Transport", "Train tickets", "2024-08-10", None),
    (10, 3, 75.00, "AUD", "Deposit", "Income", "Side gig", "2024-08-11", None),
    (11, 1, -68.50, "AUD", "Withdrawal", "Groceries", "Weekly grocery haul", "2026-09-01", None),
    (12, 1, -22.40, "AUD", "Withdrawal", "Dining Out", "Lunch at cafe", "2026-09-02", None),
    (13, 1, -18.25, "AUD", "Withdrawal", "Transport", "Train top-up", "2026-09-03", None),
    (14, 1, -94.90, "AUD", "Withdrawal", "Shopping", "Home essentials", "2026-09-04", None),
    (15, 1, -48.00, "AUD", "Withdrawal", "Utilities", "Electricity bill", "2026-09-05", None),
    (16, 1, -32.75, "AUD", "Withdrawal", "Entertainment", "Movie tickets", "2026-09-06", None),
    (17, 1, -14.99, "AUD", "Withdrawal", "Subscriptions", "Streaming service", "2026-09-07", None),
    (18, 1, -61.20, "AUD", "Withdrawal", "Groceries", "Fresh produce", "2026-09-09", None),
    (19, 1, -27.80, "AUD", "Withdrawal", "Dining Out", "Dinner with friends", "2026-09-10", None),
    (20, 1, -16.50, "AUD", "Withdrawal", "Transport", "Fuel top-up", "2026-09-11", None),
    (21, 1, -120.00, "AUD", "Withdrawal", "Shopping", "New headphones", "2026-09-12", None),
    (22, 1, -79.40, "AUD", "Withdrawal", "Utilities", "Internet bill", "2026-09-13", None),
    (23, 1, -38.00, "AUD", "Withdrawal", "Entertainment", "Concert tickets", "2026-09-14", None),
    (24, 1, -12.99, "AUD", "Withdrawal", "Subscriptions", "Cloud storage", "2026-09-16", None),
    (25, 1, -55.10, "AUD", "Withdrawal", "Groceries", "Household staples", "2026-09-18", None),
    (26, 1, -180.00, "AUD", "Withdrawal", "Dining Out", "Restaurant weekend", "2026-09-19", None),
    (27, 1, -95.00, "AUD", "Withdrawal", "Dining Out", "Uber Eats", "2026-09-20", None),
    (28, 1, -260.00, "AUD", "Withdrawal", "Shopping", "New jacket", "2026-09-21", None),
    (29, 1, -140.00, "AUD", "Withdrawal", "Transport", "Fuel + parking", "2026-09-22", None),
    (30, 1, -75.00, "AUD", "Withdrawal", "Utilities", "Water bill", "2026-09-23", None),
    (31, 1, -26.00, "AUD", "Withdrawal", "Entertainment", "Board game cafe", "2026-09-24", None),
]
cursor.executemany(
    """
    INSERT INTO transactions (
        transaction_id, account_id, amount, currency, type, category, description, date, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    transactions,
)

conn.commit()
conn.close()

print(f"Database created successfully: {DATABASE_NAME}")
