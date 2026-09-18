# Stand-in sample data used when TRANSACTIONS_SOURCE=seed, and the fallback
# whenever TRANSACTIONS_SOURCE=http but the Transactions service is unreachable
# (the Adapt step in transactions_source.fetch_transactions).
#
# Field names match the Transactions service response exactly, so a live
# response scans through rule_engine.py with no translation.

TRANSACTIONS = [
    {
        "transaction_id": 201, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Corner Store",
        "amount": 80.00, "date": "2026-09-01T10:00:00", "category": "shopping",
    },
    {
        "transaction_id": 202, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Corner Store",
        "amount": 45.00, "date": "2026-09-01T10:02:00", "category": "shopping",
    },
    {
        "transaction_id": 203, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Gas Station",
        "amount": 60.00, "date": "2026-09-01T10:04:00", "category": "transportation",
    },
    {
        "transaction_id": 204, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Coffee Shop",
        "amount": 30.00, "date": "2026-09-01T10:06:00", "category": "dining",
    },
    {
        "transaction_id": 205, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Pharmacy",
        "amount": 90.00, "date": "2026-09-01T10:08:00", "category": "healthcare",
    },
    {
        "transaction_id": 206, "customer_id": 3, "account_id": 3, "type": "withdrawal",
        "description": "Newsstand",
        "amount": 20.00, "date": "2026-09-01T10:09:00", "category": "shopping",
    },
    {
        "transaction_id": 207, "customer_id": 1, "account_id": 1, "type": "transfer",
        "description": "Unknown Vendor",
        "amount": 8000.00, "date": "2026-09-01T11:00:00", "category": "other",
    },
    {
        "transaction_id": 208, "customer_id": 5, "account_id": 5, "type": "transfer",
        "description": "Luxury Yachts",
        "amount": 22000.00, "date": "2026-09-01T12:00:00", "category": "other",
    },
    {
        "transaction_id": 209, "customer_id": 7, "account_id": 7, "type": "withdrawal",
        "description": "24/7 Diner",
        "amount": 150.00, "date": "2026-09-01T03:20:00", "category": "dining",
    },
    {
        "transaction_id": 210, "customer_id": 8, "account_id": 8, "type": "transfer",
        "description": "Familiar Store",
        "amount": 200.00, "date": "2026-09-01T09:00:00", "category": "shopping",
    },
    {
        "transaction_id": 211, "customer_id": 8, "account_id": 8, "type": "transfer",
        "description": "Crypto Exchange XYZ",
        "amount": 3500.00, "date": "2026-09-01T13:00:00", "category": "transfer",
    },
    {
        "transaction_id": 212, "customer_id": 4, "account_id": 4, "type": "transfer",
        "description": "Overseas Remit Co",
        "amount": 1200.00, "date": "2026-09-01T14:00:00", "category": "transfer",
    },
    {
        "transaction_id": 213, "customer_id": 2, "account_id": 2, "type": "withdrawal",
        "description": "Supermarket",
        "amount": 55.00, "date": "2026-09-01T15:00:00", "category": "groceries",
    },
    {
        "transaction_id": 214, "customer_id": 6, "account_id": 6, "type": "withdrawal",
        "description": "Bakery",
        "amount": 40.00, "date": "2026-09-01T16:00:00", "category": "dining",
    },
    {
        "transaction_id": 215, "customer_id": 8, "account_id": 8, "type": "withdrawal",
        "description": "Bus Fare",
        "amount": 25.00, "date": "2026-09-01T17:00:00", "category": "transportation",
    },
]
