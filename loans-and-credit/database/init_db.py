import os
import sqlite3

DATA_DIR = "/app/data"
DATABASE_NAME = os.path.join(DATA_DIR, "loans_and_credit.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute("PRAGMA foreign_keys = ON")

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
    (3, 3, "Mortgage", 250000.00, "Home Purchase", "2023-03-10", "Rejected", 3.5, None),
    (4, 4, "Student Loan", 20000.00, "Education Expenses", "2023-04-05", "Approved", 6.0, 20000.00),
    (5, 5, "Business Loan", 100000.00, "Business Expansion", "2023-05-12", "Pending", 7.0, None),
    (6, 6, "Personal Loan", 8000.00, "Medical Expenses","2023-06-18", "Approved", 5.0, 8000.00),
    (7, 7, "Auto Loan", 20000.00, "Car Purchase", "2023-07-22", "Pending", 4.5, None),
    (8, 8, "Mortgage", 300000.00, "Home Purchase", "2023-08-15", "Approved", 3.0, 300000.00),
    (9, 9, "Student Loan", 15000.00, "Education Expenses", "2023-09-10", "Rejected", 6.5, None),
    (10, 10, "Business Loan", 50000.00, "Business Expansion","2023-10-05", "Approved", 7.5, 50000.00)
]

cursor.executemany("""
    INSERT INTO loan_applications (
        loan_id,
        customer_id,
        loan_type,
        requested_amount,
        loan_purpose,
        application_date,
        status,
        interest_rate,
        approved_amount
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", loans)

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

        FOREIGN KEY (loan_id)
            REFERENCES loan_applications(loan_id)
            ON DELETE CASCADE
    )
""")

cursor.execute("DELETE FROM repayments")


repayments = [
    (1, 1, "2023-02-15", 450.00, 427.08, 22.92, 450.00, "2023-02-14", "Paid"),
    (2, 1, "2023-03-15", 450.00, 429.04, 20.96, 450.00, "2023-03-15", "Paid"),
    (3, 1, "2023-04-15", 450.00, 431.00, 19.00, 0.00, None, "Pending"),
    (4, 4, "2023-05-05", 400.00, 300.00, 100.00, 400.00, "2023-05-04", "Paid"),
    (5, 4, "2023-06-05", 400.00, 302.00, 98.00, 400.00, "2023-06-05", "Paid"),
    (6, 6, "2023-07-18", 350.00, 316.67, 33.33, 350.00, "2023-07-18", "Paid"),
    (7, 6, "2023-08-18", 350.00, 318.00, 32.00, 0.00, None, "Pending"),
    (8, 8, "2023-09-15", 1200.00, 450.00, 750.00, 1200.00, "2023-09-14", "Paid"),
    (9, 8, "2023-10-15", 1200.00, 451.13, 748.87, 1200.00, "2023-10-15", "Paid"),
    (10, 10, "2023-11-05", 600.00, 287.50, 312.50, 0.00, None, "Pending")
]

cursor.executemany("""
    INSERT INTO repayments (
        repayment_id,
        loan_id,
        due_date,
        payment_amount,
        principal_amount,
        interest_amount,
        amount_paid,
        payment_date,
        payment_status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", repayments)

conn.commit()

conn.close()

print(f"Database created successfully: {DATABASE_NAME}")