import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "fraud.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute("PRAGMA foreign_keys = ON")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS alert_rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT NOT NULL,
        rule_type TEXT NOT NULL,
        threshold_value REAL NOT NULL,
        threshold_secondary REAL,
        severity TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
""")

cursor.execute("DELETE FROM alert_rules")

rules = [
    (1, "Large Transaction Alert", "amount_over", 5000, None, "high", 1, "2026-08-01T09:00:00"),
    (2, "Very Large Transaction Alert", "amount_over", 10000, None, "high", 1, "2026-08-01T09:00:00"),
    (3, "Moderate Transaction Alert", "amount_over", 2000, None, "medium", 0, "2026-08-01T09:00:00"),
    (4, "Extreme Transaction Alert", "amount_over", 20000, None, "high", 1, "2026-08-01T09:00:00"),
    (5, "Rapid Transactions", "velocity", 5, 10, "high", 1, "2026-08-01T09:00:00"),
    (6, "Frequent Small Transfers", "velocity", 3, 30, "medium", 1, "2026-08-01T09:00:00"),
    (7, "Late Night Activity", "unusual_time", 0, 5, "medium", 1, "2026-08-01T09:00:00"),
    (8, "Early Morning Activity", "unusual_time", 1, 4, "low", 0, "2026-08-01T09:00:00"),
    (9, "New Recipient High Value", "new_recipient_high_value", 2000, None, "high", 1, "2026-08-01T09:00:00"),
    (10, "New Recipient Moderate Value", "new_recipient_high_value", 1000, None, "medium", 1, "2026-08-01T09:00:00"),
]

cursor.executemany("""
    INSERT INTO alert_rules (
        rule_id, rule_name, rule_type, threshold_value, threshold_secondary,
        severity, enabled, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", rules)

cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        transaction_id INTEGER NOT NULL,
        transaction_amount REAL NOT NULL,
        transaction_recipient TEXT,
        transaction_datetime TEXT,
        transaction_category TEXT,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        ai_explanation TEXT,
        explanation_generated_at TEXT,
        created_at TEXT NOT NULL,

        FOREIGN KEY (rule_id) REFERENCES alert_rules(rule_id),
        UNIQUE (rule_id, transaction_id)
    )
""")

cursor.execute("DELETE FROM alerts")

alerts = [
    (1, 1, 1, 101, 7500.00, "Unknown Pty Ltd", "2026-08-20T14:32:00", "transfer", "high", "new", None, None, "2026-08-20T14:32:05"),
    (2, 2, 2, 102, 15000.00, "Global Traders Inc", "2026-08-21T09:15:00", "transfer", "high", "reviewed",
     "This transaction exceeded the $10,000 threshold rule and was flagged for manual review.", "2026-08-21T09:20:00", "2026-08-21T09:15:05"),
    (3, 5, 3, 103, 450.00, "QuickMart", "2026-08-22T11:00:00", "shopping", "high", "new", None, None, "2026-08-22T11:00:05"),
    (4, 7, 4, 104, 899.00, "Night Owl Electronics", "2026-08-23T02:14:00", "shopping", "medium", "confirmed",
     "Flagged because the transaction occurred at 2:14am, outside the customer's usual active hours.", "2026-08-23T02:20:00", "2026-08-23T02:14:05"),
    (5, 9, 5, 105, 3200.00, "Overseas Holdings", "2026-08-24T16:45:00", "transfer", "high", "new", None, None, "2026-08-24T16:45:05"),
    (6, 1, 6, 106, 6100.00, "Home Renovations Co", "2026-08-25T10:20:00", "other", "high", "dismissed",
     "Customer confirmed this was a planned renovation payment; not fraudulent.", "2026-08-25T10:30:00", "2026-08-25T10:20:05"),
    (7, 6, 7, 107, 120.00, "Cafe Central", "2026-08-26T08:05:00", "dining", "medium", "new", None, None, "2026-08-26T08:05:05"),
    (8, 10, 8, 108, 1500.00, "Bright Future Investments", "2026-08-27T13:30:00", "transfer", "medium", "reviewed",
     "First transfer to this recipient above the $1,000 threshold; recommend confirming with the customer.", "2026-08-27T13:35:00", "2026-08-27T13:30:05"),
    (9, 4, 9, 109, 25000.00, "Luxury Motors", "2026-08-28T17:00:00", "other", "high", "new", None, None, "2026-08-28T17:00:05"),
    (10, 7, 10, 110, 340.00, "24hr Pharmacy", "2026-08-29T03:45:00", "healthcare", "medium", "confirmed",
     "Legitimate emergency pharmacy purchase, confirmed with the customer.", "2026-08-29T03:50:00", "2026-08-29T03:45:05"),
    (11, 2, 1, 111, 12000.00, "Property Deposit Account", "2026-08-30T12:00:00", "transfer", "high", "new", None, None, "2026-08-30T12:00:05"),
    (12, 5, 2, 112, 275.00, "FastFood Express", "2026-08-31T19:10:00", "dining", "high", "dismissed",
     "Multiple transactions were the customer's family members using a shared account; verified legitimate.", "2026-08-31T19:15:00", "2026-08-31T19:10:05"),
]

cursor.executemany("""
    INSERT INTO alerts (
        alert_id, rule_id, customer_id, transaction_id, transaction_amount,
        transaction_recipient, transaction_datetime, transaction_category,
        severity, status, ai_explanation, explanation_generated_at, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", alerts)

conn.commit()
conn.close()

print(f"Database created successfully: {DATABASE_NAME}")
