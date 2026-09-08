import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "loans_and_credit.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

# Loan Applications table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS loan_applications (
        loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        loan_type TEXT NOT NULL,
        requested_amount REAL NOT NULL,
        loan_purpose TEXT NOT NULL,
        application_date TEXT NOT NULL,
        status TEXT NOT NULL,
        interest_rate REAL NOT NULL,
        approved_amount REAL
    )
""")
cursor.execute("DELETE FROM loan_applications")

loans = [
    (1, 1, "Personal Loan", 5000.00, "Home Renovation", "2023-01-15", "Approved", 5.5, 5000.00),
    (2, 2, "Auto Loan", 15000.00, "Car Purchase", "2023-02-20", "Pending", 4.0, None),
    (3, 3, "Mortgage", 250000.00, "Home Purchase", "2023-03-10", "Rejected", 3.5, None)
]

cursor.executemany(
    """
    INSERT INTO loan_applications (
        loan_id, customer_id, loan_type, requested_amount,
        loan_purpose, application_date, status, interest_rate, approved_amount
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    loans,
)

# Repayments tables
cursor.execute("""
    CREATE TABLE IF NOT EXISTS repayments (
        repayment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_id INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        payment_amount REAL NOT NULL,
        principal_amount REAL NOT NULL,
        interest_amount REAL NOT NULL,
        amount_paid REAL DEFAULT 0,
        payment_date TEXT,
        payment_status TEXT NOT NULL,
        FOREIGN KEY (loan_id) REFERENCES loan_applications(loan_id) ON DELETE CASCADE
    )
""")
cursor.execute("DELETE FROM repayments")

repayments = [
    (1, 1, "2023-02-15", 450.00, 427.08, 22.92, 450.00, "2023-02-14", "Paid"),
    (2, 1, "2023-03-15", 450.00, 429.04, 20.96, 450.00, "2023-03-15", "Paid")
]

cursor.executemany(
    """
    INSERT INTO repayments (
        repayment_id, loan_id, due_date, payment_amount,
        principal_amount, interest_amount, amount_paid, payment_date, payment_status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    repayments,
)

conn.commit()

conn.close()

print(f"Database created successfully: {DATABASE_NAME}")