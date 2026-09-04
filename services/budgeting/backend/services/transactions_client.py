"""Typed HTTP client for the Transactions feature (Student 5).

Cross-feature rule: actual spending is only ever read over HTTP from the
Transactions service API. This module never touches another feature's
SQLite file.

The Transactions service may not be running yet, so the client falls back to
a realistic mock dataset. Behaviour is controlled by USE_MOCK_TRANSACTIONS:

    auto   (default) - try the real API, fall back to mock on any failure
    true             - always use the mock dataset
    false            - always use the real API and surface errors
"""

import os

import requests


TRANSACTIONS_SERVICE_URL = os.getenv(
    "TRANSACTIONS_SERVICE_URL", "http://localhost:5005"
)
USE_MOCK_TRANSACTIONS = os.getenv("USE_MOCK_TRANSACTIONS", "auto").strip().lower()
TIMEOUT = 5

# Candidate paths, because the Transactions API contract is not final yet.
CANDIDATE_PATHS = ("/api/transactions", "/transactions")


# ---------------------------------------------------------------------------
# Mock dataset - used when the Transactions service is unavailable
# ---------------------------------------------------------------------------

# (customer_id, year, month, category, day, merchant, amount)
_MOCK_ROWS = [
    # ---- Customer 1, September 2026 -------------------------------------
    (1, 2026, 9, "Groceries", 1, "Woolworths Metro", 132.40),
    (1, 2026, 9, "Groceries", 5, "Coles", 98.75),
    (1, 2026, 9, "Groceries", 9, "Aldi", 76.20),
    (1, 2026, 9, "Groceries", 14, "Woolworths Metro", 145.60),
    (1, 2026, 9, "Groceries", 19, "Harris Farm Markets", 89.05),
    (1, 2026, 9, "Groceries", 24, "Coles", 103.00),

    (1, 2026, 9, "Dining Out", 2, "Uber Eats", 42.50),
    (1, 2026, 9, "Dining Out", 3, "Cafe Bones", 18.00),
    (1, 2026, 9, "Dining Out", 6, "Thai Palace", 76.80),
    (1, 2026, 9, "Dining Out", 9, "DoorDash", 55.20),
    (1, 2026, 9, "Dining Out", 12, "Sushi Train", 34.50),
    (1, 2026, 9, "Dining Out", 15, "Pizza Union", 48.00),
    (1, 2026, 9, "Dining Out", 18, "Uber Eats", 62.00),
    (1, 2026, 9, "Dining Out", 21, "Cafe Bones", 22.00),
    (1, 2026, 9, "Dining Out", 25, "Nando's", 53.00),

    (1, 2026, 9, "Transport", 1, "Opal top-up", 50.00),
    (1, 2026, 9, "Transport", 7, "Ampol", 78.40),
    (1, 2026, 9, "Transport", 11, "Uber", 24.60),
    (1, 2026, 9, "Transport", 17, "Uber", 31.00),
    (1, 2026, 9, "Transport", 23, "Opal top-up", 34.00),

    (1, 2026, 9, "Entertainment", 6, "Hoyts Cinemas", 28.00),
    (1, 2026, 9, "Entertainment", 13, "Steam", 44.00),
    (1, 2026, 9, "Entertainment", 20, "Ticketek", 18.00),

    (1, 2026, 9, "Utilities", 4, "AGL Energy", 142.30),
    (1, 2026, 9, "Utilities", 10, "Sydney Water", 51.70),
    (1, 2026, 9, "Utilities", 16, "Aussie Broadband", 46.00),

    (1, 2026, 9, "Shopping", 8, "JB Hi-Fi", 329.00),
    (1, 2026, 9, "Shopping", 15, "Uniqlo", 89.95),
    (1, 2026, 9, "Shopping", 22, "Kmart", 86.05),

    (1, 2026, 9, "Subscriptions", 1, "Netflix", 25.99),
    (1, 2026, 9, "Subscriptions", 1, "Spotify", 13.99),
    (1, 2026, 9, "Subscriptions", 2, "Apple iCloud", 19.99),

    # ---- Customer 1, August 2026 (history for trend questions) ----------
    (1, 2026, 8, "Groceries", 3, "Woolworths Metro", 210.50),
    (1, 2026, 8, "Groceries", 11, "Coles", 188.20),
    (1, 2026, 8, "Groceries", 19, "Aldi", 156.30),
    (1, 2026, 8, "Groceries", 27, "Woolworths Metro", 157.00),

    (1, 2026, 8, "Dining Out", 5, "Uber Eats", 68.00),
    (1, 2026, 8, "Dining Out", 12, "Thai Palace", 82.00),
    (1, 2026, 8, "Dining Out", 20, "Cafe Bones", 24.00),
    (1, 2026, 8, "Dining Out", 28, "DoorDash", 94.00),

    (1, 2026, 8, "Transport", 2, "Opal top-up", 60.00),
    (1, 2026, 8, "Transport", 14, "Ampol", 91.00),
    (1, 2026, 8, "Transport", 25, "Uber", 44.00),

    # ---- Customer 2, September 2026 -------------------------------------
    (2, 2026, 9, "Groceries", 2, "Coles", 112.00),
    (2, 2026, 9, "Groceries", 12, "Aldi", 86.50),
    (2, 2026, 9, "Groceries", 22, "Woolworths Metro", 69.50),

    (2, 2026, 9, "Dining Out", 4, "Guzman y Gomez", 38.00),
    (2, 2026, 9, "Dining Out", 8, "Uber Eats", 71.00),
    (2, 2026, 9, "Dining Out", 14, "Cafe Dolce", 26.00),
    (2, 2026, 9, "Dining Out", 19, "Ramen Ya", 58.00),
    (2, 2026, 9, "Dining Out", 26, "DoorDash", 47.00),

    (2, 2026, 9, "Health", 7, "Chemist Warehouse", 42.00),
    (2, 2026, 9, "Health", 15, "Fitness First", 53.00),

    (2, 2026, 9, "Education", 5, "Co-op Bookshop", 350.00),
]


def _mock_transactions(customer_id, month, year):
    transactions = []
    for index, row in enumerate(_MOCK_ROWS, start=1):
        cust, yr, mth, category, day, merchant, amount = row
        if customer_id is not None and int(cust) != int(customer_id):
            continue
        if month is not None and int(mth) != int(month):
            continue
        if year is not None and int(yr) != int(year):
            continue
        transactions.append(
            {
                "transaction_id": index,
                "customer_id": cust,
                "amount": amount,
                "category": category,
                "transaction_date": f"{yr:04d}-{mth:02d}-{day:02d}",
                "description": merchant,
                "transaction_type": "withdrawal",
            }
        )
    return transactions


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------

_AMOUNT_KEYS = ("amount", "transaction_amount", "value")
_CATEGORY_KEYS = ("category", "transaction_category", "ai_category")
_DATE_KEYS = ("transaction_date", "date", "transaction_datetime", "created_at")
_DESCRIPTION_KEYS = ("description", "merchant", "recipient", "notes")
_TYPE_KEYS = ("transaction_type", "type")


def _first(record, keys, default=None):
    for key in keys:
        if record.get(key) not in (None, ""):
            return record[key]
    return default


def _normalise(payload):
    """Accept the shapes the Transactions API might plausibly return."""
    if isinstance(payload, dict):
        for key in ("transactions", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            payload = []

    if not isinstance(payload, list):
        return []

    normalised = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        try:
            amount = abs(float(_first(record, _AMOUNT_KEYS, 0) or 0))
        except (TypeError, ValueError):
            continue
        normalised.append(
            {
                "transaction_id": _first(record, ("transaction_id", "id")),
                "customer_id": record.get("customer_id"),
                "amount": amount,
                "category": _first(record, _CATEGORY_KEYS, "Uncategorised"),
                "transaction_date": str(_first(record, _DATE_KEYS, ""))[:10],
                "description": _first(record, _DESCRIPTION_KEYS, ""),
                "transaction_type": _first(record, _TYPE_KEYS, "withdrawal"),
            }
        )
    return normalised


def _fetch_live(customer_id, month, year):
    params = _month_bounds(month, year)
    if customer_id is not None:
        params["customer_id"] = customer_id

    last_error = None
    for path in CANDIDATE_PATHS:
        try:
            response = requests.get(
                f"{TRANSACTIONS_SERVICE_URL}{path}", params=params, timeout=TIMEOUT
            )
            if response.status_code == 404:
                last_error = f"404 from {path}"
                continue
            response.raise_for_status()
            return _normalise(response.json())
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"Transactions service unavailable: {last_error}")


def _month_bounds(month, year):
    if month is None or year is None:
        return {}
    month = int(month)
    year = int(year)
    if month == 12:
        next_month, next_year = 1, year + 1
    else:
        next_month, next_year = month + 1, year
    return {
        "date_from": f"{year:04d}-{month:02d}-01",
        "date_to": f"{next_year:04d}-{next_month:02d}-01",
        "month": month,
        "year": year,
    }


def _in_period(transaction, month, year):
    date = str(transaction.get("transaction_date") or "")
    if len(date) < 7 or month is None or year is None:
        return True
    try:
        return int(date[:4]) == int(year) and int(date[5:7]) == int(month)
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_transactions(customer_id=None, month=None, year=None):
    """Return (transactions, source) where source is 'transactions-api' or 'mock'."""
    if USE_MOCK_TRANSACTIONS in ("true", "1", "yes", "on"):
        return _mock_transactions(customer_id, month, year), "mock"

    try:
        live = _fetch_live(customer_id, month, year)
    except Exception:
        if USE_MOCK_TRANSACTIONS in ("false", "0", "no", "off"):
            raise
        return _mock_transactions(customer_id, month, year), "mock"

    # The upstream service may ignore our date filters, so filter locally too.
    live = [t for t in live if _in_period(t, month, year)]
    return live, "transactions-api"


def spend_by_category(customer_id=None, month=None, year=None):
    """Total withdrawal spend per category for one customer and month."""
    transactions, source = get_transactions(customer_id, month, year)

    totals = {}
    for transaction in transactions:
        if str(transaction.get("transaction_type", "")).lower() == "deposit":
            continue
        category = transaction.get("category") or "Uncategorised"
        totals[category] = round(totals.get(category, 0.0) + transaction["amount"], 2)

    return totals, source, transactions
