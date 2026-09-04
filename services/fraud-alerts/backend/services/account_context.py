import os

import requests

ACCOUNTS_SERVICE_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001")
TIMEOUT = 5


def fetch_account_context(customer_id):
    """Best-effort account context for AI explanations. Returns None if the
    Accounts service is unreachable or doesn't have this customer yet -
    Accounts is optional per spec, so explanations degrade rather than fail."""
    try:
        response = requests.get(f"{ACCOUNTS_SERVICE_URL}/customers/{customer_id}", timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None
