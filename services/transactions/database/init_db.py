import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "transactions.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

# Customers table
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
    (2, "William", "Por", "will@example.com", "+61400000001", "1990-05-12", "2 High St", None, None),
    (3, "Maya", "Nguyen", "maya@example.com", "+61400000002", "1997-07-11", "9 River Rd", None, None),
]
cursor.executemany(
    """
    INSERT INTO customers (
        customer_id, first_name, last_name, email, phone, date_of_birth, address, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    customers,
)

# Accounts table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        account_number TEXT NOT NULL,
        account_type TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'AUD',
        status TEXT NOT NULL DEFAULT 'Active',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT,
        FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE
    )
""")
cursor.execute("DELETE FROM accounts")
accounts = [
    (1001, 1, "ACC1001001", "Checking", 1250.00, "AUD", "Active", None, None),
    (1002, 2, "ACC1002002", "Savings", 2800.00, "AUD", "Active", None, None),
    (1003, 3, "ACC1003003", "Credit", -420.25, "AUD", "Active", None, None),
]
cursor.executemany(
    """
    INSERT INTO accounts (
        account_id, customer_id, account_number, account_type, balance, currency, status, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    accounts,
)

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
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
    )
""")
cursor.execute("DELETE FROM transactions")
transactions = [
    (1, 1001, 250.00, "AUD", "Deposit", "Salary", "Monthly salary", "2024-08-01", None),
    (2, 1001, -50.25, "AUD", "Withdrawal", "Groceries", "Supermarket", "2024-08-02", None),
    (3, 1002, -120.00, "AUD", "Transfer", "Rent", "August rent", "2024-08-03", None),
    (4, 1003, 500.00, "AUD", "Deposit", "Income", "Refund", "2024-08-05", None),
    (5, 1003, -80.00, "AUD", "Withdrawal", "Dining", "Dinner with team", "2024-08-06", None),
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
