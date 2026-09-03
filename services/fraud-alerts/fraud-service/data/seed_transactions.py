# Stand-in sample data used when TRANSACTIONS_SOURCE=seed (the default). No real
# Transactions service exists yet in this repo, so detection scans this fixture
# instead. Field names match the `transactions` table in the team's build spec,
# so a real Transactions service response can be dropped in later with no
# changes needed in rule_engine.py.

TRANSACTIONS = [
    {
        "transaction_id": 201, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Corner Store",
        "amount": 80.00, "datetime_sent": "2026-09-01T10:00:00", "generated_category": "shopping",
    },
    {
        "transaction_id": 202, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Corner Store",
        "amount": 45.00, "datetime_sent": "2026-09-01T10:02:00", "generated_category": "shopping",
    },
    {
        "transaction_id": 203, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Gas Station",
        "amount": 60.00, "datetime_sent": "2026-09-01T10:04:00", "generated_category": "transportation",
    },
    {
        "transaction_id": 204, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Coffee Shop",
        "amount": 30.00, "datetime_sent": "2026-09-01T10:06:00", "generated_category": "dining",
    },
    {
        "transaction_id": 205, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Pharmacy",
        "amount": 90.00, "datetime_sent": "2026-09-01T10:08:00", "generated_category": "healthcare",
    },
    {
        "transaction_id": 206, "customer_id": 3, "account_id": 3, "transaction_type": "withdrawal",
        "sender_name": "Customer 3", "recipient_name": "Newsstand",
        "amount": 20.00, "datetime_sent": "2026-09-01T10:09:00", "generated_category": "shopping",
    },
    {
        "transaction_id": 207, "customer_id": 1, "account_id": 1, "transaction_type": "transfer",
        "sender_name": "Customer 1", "recipient_name": "Unknown Vendor",
        "amount": 8000.00, "datetime_sent": "2026-09-01T11:00:00", "generated_category": "other",
    },
    {
        "transaction_id": 208, "customer_id": 5, "account_id": 5, "transaction_type": "transfer",
        "sender_name": "Customer 5", "recipient_name": "Luxury Yachts",
        "amount": 22000.00, "datetime_sent": "2026-09-01T12:00:00", "generated_category": "other",
    },
    {
        "transaction_id": 209, "customer_id": 7, "account_id": 7, "transaction_type": "withdrawal",
        "sender_name": "Customer 7", "recipient_name": "24/7 Diner",
        "amount": 150.00, "datetime_sent": "2026-09-01T03:20:00", "generated_category": "dining",
    },
    {
        "transaction_id": 210, "customer_id": 9, "account_id": 9, "transaction_type": "transfer",
        "sender_name": "Customer 9", "recipient_name": "Familiar Store",
        "amount": 200.00, "datetime_sent": "2026-09-01T09:00:00", "generated_category": "shopping",
    },
    {
        "transaction_id": 211, "customer_id": 9, "account_id": 9, "transaction_type": "transfer",
        "sender_name": "Customer 9", "recipient_name": "Crypto Exchange XYZ",
        "amount": 3500.00, "datetime_sent": "2026-09-01T13:00:00", "generated_category": "transfer",
    },
    {
        "transaction_id": 212, "customer_id": 4, "account_id": 4, "transaction_type": "transfer",
        "sender_name": "Customer 4", "recipient_name": "Overseas Remit Co",
        "amount": 1200.00, "datetime_sent": "2026-09-01T14:00:00", "generated_category": "transfer",
    },
    {
        "transaction_id": 213, "customer_id": 2, "account_id": 2, "transaction_type": "withdrawal",
        "sender_name": "Customer 2", "recipient_name": "Supermarket",
        "amount": 55.00, "datetime_sent": "2026-09-01T15:00:00", "generated_category": "groceries",
    },
    {
        "transaction_id": 214, "customer_id": 6, "account_id": 6, "transaction_type": "withdrawal",
        "sender_name": "Customer 6", "recipient_name": "Bakery",
        "amount": 40.00, "datetime_sent": "2026-09-01T16:00:00", "generated_category": "dining",
    },
    {
        "transaction_id": 215, "customer_id": 8, "account_id": 8, "transaction_type": "withdrawal",
        "sender_name": "Customer 8", "recipient_name": "Bus Fare",
        "amount": 25.00, "datetime_sent": "2026-09-01T17:00:00", "generated_category": "transportation",
    },
]
