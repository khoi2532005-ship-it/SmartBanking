import os

import requests

from data.seed_transactions import TRANSACTIONS as SEED_TRANSACTIONS

TRANSACTIONS_SOURCE = os.getenv("TRANSACTIONS_SOURCE", "seed").strip().lower()
TRANSACTIONS_SERVICE_URL = os.getenv("TRANSACTIONS_SERVICE_URL", "http://localhost:5005")
TIMEOUT = 5


def fetch_transactions():
    """Returns (transactions, degraded). degraded=True means TRANSACTIONS_SOURCE=http
    was configured but the real Transactions service was unreachable, so this fell
    back to the local seed fixture instead of failing outright (the Adapt step)."""
    if TRANSACTIONS_SOURCE == "http":
        try:
            response = requests.get(f"{TRANSACTIONS_SERVICE_URL}/transactions", timeout=TIMEOUT)
            response.raise_for_status()
            return response.json(), False
        except Exception:
            return SEED_TRANSACTIONS, True

    return SEED_TRANSACTIONS, False
