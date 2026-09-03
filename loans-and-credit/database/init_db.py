import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "loans_and_credit.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

# -------------------------------
# Loans tables (existing)
# -------------------------------
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


# -------------------------------
# New tables for Transactions feature (Aidan)
# -------------------------------
cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        date_of_birth TEXT,
        address TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT
    )
""")
cursor.execute("DELETE FROM customers")

customers = [
    (1, "Aidan", "Lei", "aidan@example.com", "+61400000000", "1995-01-01", "1 Main St", None, None),
    (2, "William", "Por", "will@example.com", "+61400000001", "1990-05-12", "2 High St", None, None)
]

cursor.executemany(
    """
    INSERT INTO customers (
        customer_id, first_name, last_name, email, phone, date_of_birth, address, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    customers,
)

cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        account_number TEXT NOT NULL,
        account_type TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'USD',
        status TEXT NOT NULL DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE
    )
""")
cursor.execute("DELETE FROM accounts")

accounts = [
    (1001, 1, "ACC1001001", "Checking", 1000.00, "AUD", "Active", None, None),
    (1002, 2, "ACC1002002", "Savings", 2500.00, "AUD", "Active", None, None)
]

cursor.executemany(
    """
    INSERT INTO accounts (
        account_id, customer_id, account_number, account_type, balance, currency, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    accounts,
)

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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
    )
""")
cursor.execute("DELETE FROM transactions")

transactions = [
    (1, 1001, 250.00, "AUD", "Deposit", "Salary", "Monthly salary", "2024-08-01", None),
    (2, 1001, -50.25, "AUD", "Withdrawal", "Groceries", "Supermarket", "2024-08-02", None),
    (3, 1002, -120.00, "AUD", "Transfer", "Rent", "August rent", "2024-08-03", None)
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

print(f"Database created successfully: {DATABASE_NAME}")
