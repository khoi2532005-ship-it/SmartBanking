import os
import sqlite3

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATABASE_NAME = os.path.join(DATA_DIR, "accounts_and_customers.db")

os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute("PRAGMA foreign_keys = ON")

# ============================================================
# CUSTOMERS
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        phone TEXT,
        date_of_birth TEXT,
        address TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")

cursor.execute("DELETE FROM customers")

customers = [
    (1, "Amelia", "Turner", "amelia.turner@example.com", "0410 111 222", "1990-04-12", "12 Harbour St, Sydney NSW"),
    (2, "Noah", "Whitfield", "noah.whitfield@example.com", "0410 222 333", "1985-11-03", "45 King St, Melbourne VIC"),
    (3, "Olivia", "Nguyen", "olivia.nguyen@example.com", "0410 333 444", "1998-07-21", "8 Grey St, Brisbane QLD"),
    (4, "Liam", "Kowalski", "liam.kowalski@example.com", "0410 444 555", "1979-02-14", "3 Rundle Mall, Adelaide SA"),
    (5, "Ava", "Bianchi", "ava.bianchi@example.com", "0410 555 666", "1992-09-30", "22 Hay St, Perth WA"),
    (6, "Ethan", "Okafor", "ethan.okafor@example.com", "0410 666 777", "2001-01-08", "60 Elizabeth St, Hobart TAS"),
    (7, "Mia", "Sorensen", "mia.sorensen@example.com", "0410 777 888", "1988-05-25", "14 Smith St, Darwin NT"),
    (8, "Jack", "Petrov", "jack.petrov@example.com", "0410 888 999", "1995-12-19", "27 Northbourne Ave, Canberra ACT"),
]

cursor.executemany("""
    INSERT INTO customers (
        customer_id, first_name, last_name, email, phone, date_of_birth, address
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", customers)

# ============================================================
# ACCOUNTS
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        account_number TEXT NOT NULL UNIQUE,
        account_type TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'AUD',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),

        FOREIGN KEY (customer_id)
            REFERENCES customers(customer_id)
            ON DELETE CASCADE
    )
""")

cursor.execute("DELETE FROM accounts")

accounts = [
    (1, 1, "AC-100001", "SAVINGS", 8250.40, "AUD", "ACTIVE"),
    (2, 1, "AC-100002", "CHECKING", 1120.15, "AUD", "ACTIVE"),
    (3, 2, "AC-100003", "SAVINGS", 250.00, "AUD", "ACTIVE"),
    (4, 2, "AC-100004", "CREDIT", -430.75, "AUD", "ACTIVE"),
    (5, 3, "AC-100005", "CHECKING", 15600.00, "AUD", "ACTIVE"),
    (6, 4, "AC-100006", "SAVINGS", 0.00, "AUD", "INACTIVE"),
    (7, 5, "AC-100007", "CHECKING", 3320.90, "AUD", "ACTIVE"),
    (8, 5, "AC-100008", "SAVINGS", 42000.00, "AUD", "ACTIVE"),
    (9, 6, "AC-100009", "CHECKING", 75.20, "AUD", "ACTIVE"),
    (10, 7, "AC-100010", "SAVINGS", 980.00, "AUD", "CLOSED"),
    (11, 8, "AC-100011", "CHECKING", 6100.60, "AUD", "ACTIVE"),
]

cursor.executemany("""
    INSERT INTO accounts (
        account_id, customer_id, account_number, account_type, balance, currency, status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", accounts)

# ============================================================
# AI_SUMMARIES (generated on demand - table starts empty)
# ============================================================

cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_summaries (
        summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        summary_type TEXT NOT NULL,
        summary_text TEXT NOT NULL,
        risk_level TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),

        FOREIGN KEY (customer_id)
            REFERENCES customers(customer_id)
            ON DELETE CASCADE
    )
""")

cursor.execute("DELETE FROM ai_summaries")

conn.commit()
conn.close()

print(f"Database created successfully: {DATABASE_NAME}")
