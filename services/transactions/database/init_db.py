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
    (4, "Olivia", "Chen", "olivia@example.com", "+61400000003", "1988-03-22", "14 Harbour Ave", None, None),
    (5, "Daniel", "Patel", "daniel@example.com", "+61400000004", "1992-11-09", "27 Oak Terrace", None, None),
    (6, "Emma", "Garcia", "emma@example.com", "+61400000005", "1994-02-18", "8 Sunset Blvd", None, None),
    (7, "Ethan", "Kim", "ethan@example.com", "+61400000006", "1987-08-07", "31 Pine Lane", None, None),
    (8, "Sophia", "Fischer", "sophia@example.com", "+61400000007", "1996-06-30", "5 Meadow Walk", None, None),
    (9, "Lucas", "Brown", "lucas@example.com", "+61400000008", "1991-09-12", "19 Riverstone Dr", None, None),
    (10, "Chloe", "Davis", "chloe@example.com", "+61400000009", "1993-12-04", "7 Linden Way", None, None),
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
    (1004, 4, "ACC1004004", "Checking", 7600.00, "AUD", "Active", None, None),
    (1005, 5, "ACC1005005", "Savings", 4200.00, "AUD", "Active", None, None),
    (1006, 6, "ACC1006006", "Checking", 910.50, "AUD", "Active", None, None),
    (1007, 7, "ACC1007007", "Savings", 6500.00, "AUD", "Active", None, None),
    (1008, 8, "ACC1008008", "Credit", -210.00, "AUD", "Active", None, None),
    (1009, 9, "ACC1009009", "Checking", 1820.75, "AUD", "Active", None, None),
    (1010, 10, "ACC1010010", "Savings", 3050.25, "AUD", "Active", None, None),
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
    (5, 1003, -80.00, "AUD", "Withdrawal", "Dining Out", "Dinner with team", "2024-08-06", None),
    (6, 1001, -15.75, "AUD", "Withdrawal", "Dining Out", "Coffee shop", "2024-08-07", None),
    (7, 1002, -60.00, "AUD", "Withdrawal", "Groceries", "Weekly groceries", "2024-08-08", None),
    (8, 1001, -200.00, "AUD", "Transfer", "Utilities", "Electric bill", "2024-08-09", None),
    (9, 1003, -30.00, "AUD", "Withdrawal", "Transport", "Train tickets", "2024-08-10", None),
    (10, 1002, 75.00, "AUD", "Deposit", "Income", "Side gig", "2024-08-11", None),
    (11, 1001, -68.50, "AUD", "Withdrawal", "Groceries", "Weekly grocery haul", "2026-09-01", None),
    (12, 1001, -22.40, "AUD", "Withdrawal", "Dining Out", "Lunch at cafe", "2026-09-02", None),
    (13, 1001, -18.25, "AUD", "Withdrawal", "Transport", "Train top-up", "2026-09-03", None),
    (14, 1001, -94.90, "AUD", "Withdrawal", "Shopping", "Home essentials", "2026-09-04", None),
    (15, 1001, -48.00, "AUD", "Withdrawal", "Utilities", "Electricity bill", "2026-09-05", None),
    (16, 1001, -32.75, "AUD", "Withdrawal", "Entertainment", "Movie tickets", "2026-09-06", None),
    (17, 1001, -14.99, "AUD", "Withdrawal", "Subscriptions", "Streaming service", "2026-09-07", None),
    (18, 1001, -61.20, "AUD", "Withdrawal", "Groceries", "Fresh produce", "2026-09-09", None),
    (19, 1001, -27.80, "AUD", "Withdrawal", "Dining Out", "Dinner with friends", "2026-09-10", None),
    (20, 1001, -16.50, "AUD", "Withdrawal", "Transport", "Fuel top-up", "2026-09-11", None),
    (21, 1001, -120.00, "AUD", "Withdrawal", "Shopping", "New headphones", "2026-09-12", None),
    (22, 1001, -79.40, "AUD", "Withdrawal", "Utilities", "Internet bill", "2026-09-13", None),
    (23, 1001, -38.00, "AUD", "Withdrawal", "Entertainment", "Concert tickets", "2026-09-14", None),
    (24, 1001, -12.99, "AUD", "Withdrawal", "Subscriptions", "Cloud storage", "2026-09-16", None),
    (25, 1001, -55.10, "AUD", "Withdrawal", "Groceries", "Household staples", "2026-09-18", None),
    (26, 1001, -180.00, "AUD", "Withdrawal", "Dining Out", "Restaurant weekend", "2026-09-19", None),
    (27, 1001, -95.00, "AUD", "Withdrawal", "Dining Out", "Uber Eats", "2026-09-20", None),
    (28, 1001, -260.00, "AUD", "Withdrawal", "Shopping", "New jacket", "2026-09-21", None),
    (29, 1001, -140.00, "AUD", "Withdrawal", "Transport", "Fuel + parking", "2026-09-22", None),
    (30, 1001, -75.00, "AUD", "Withdrawal", "Utilities", "Water bill", "2026-09-23", None),
    (31, 1001, -26.00, "AUD", "Withdrawal", "Entertainment", "Board game cafe", "2026-09-24", None),
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
