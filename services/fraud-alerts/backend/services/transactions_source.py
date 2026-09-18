import os

import requests

from data.seed_transactions import TRANSACTIONS as SEED_TRANSACTIONS

TRANSACTIONS_SOURCE = os.getenv("TRANSACTIONS_SOURCE", "seed").strip().lower()
TRANSACTIONS_SERVICE_URL = os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005")
TIMEOUT = 5


def _scannable(txn):
    """Drops or corrects the two things the rules cannot handle on their own.
    Returns None for a record that cannot be scanned at all.

    Field names now match the Transactions service directly, so there is no
    mapping to do here - only these two corrections:

      - customer_id may be NULL (the service LEFT JOINs accounts, and a
        transaction whose account_id does not resolve comes back without one).
        alerts.customer_id is NOT NULL, and velocity / new-recipient group by it.
      - amount is signed: withdrawals are negative. The threshold rules compare
        magnitude, so a -7500 withdrawal has to read as 7500.
    """
    if txn.get("customer_id") is None:
        return None

    try:
        amount = abs(float(txn.get("amount")))
    except (TypeError, ValueError):
        return None

    return {**txn, "amount": amount}


def fetch_transactions():
    """Returns (transactions, degraded). degraded=True means TRANSACTIONS_SOURCE=http
    was configured but the real Transactions service was unreachable - or returned
    nothing this service could scan - so this fell back to the local seed fixture
    instead of failing outright (the Adapt step)."""
    if TRANSACTIONS_SOURCE == "http":
        try:
            response = requests.get(f"{TRANSACTIONS_SERVICE_URL}/api/transactions", timeout=TIMEOUT)
            response.raise_for_status()
            scannable = [t for t in (_scannable(t) for t in response.json()) if t is not None]
        except Exception:
            return SEED_TRANSACTIONS, True

        # A live response every record of which had to be dropped is no more
        # useful than an unreachable service - treat it the same way.
        if not scannable:
            return SEED_TRANSACTIONS, True
        return scannable, False

    return SEED_TRANSACTIONS, False
