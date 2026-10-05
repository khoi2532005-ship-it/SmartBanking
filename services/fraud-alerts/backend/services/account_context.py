import os

import requests

ACCOUNTS_SERVICE_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001")
TIMEOUT = 5

# The only account fields an explanation needs. The customer record also has
# name, email, phone, date of birth, address and account numbers; this text
# goes to an external LLM, so none of those are passed on.
ACCOUNT_FIELDS = ("account_type", "status", "balance", "currency")


def fetch_account_context(customer_id):
    """Best-effort account context for AI explanations: (context, problem).

    context is None when Accounts could not provide it, and problem says why.
    Accounts is optional per spec, so explanations degrade rather than fail."""
    try:
        response = requests.get(f"{ACCOUNTS_SERVICE_URL}/api/customers/{customer_id}", timeout=TIMEOUT)
    except requests.RequestException:
        return None, "Accounts service unreachable"
    if response.status_code == 404:
        return None, f"customer {customer_id} not found in Accounts"
    try:
        response.raise_for_status()
        customer = response.json()
    except (requests.RequestException, ValueError):
        return None, f"Accounts service answered HTTP {response.status_code}"
    if not isinstance(customer, dict):
        return None, "Accounts service returned an unexpected response"

    accounts = [
        {field: account.get(field) for field in ACCOUNT_FIELDS}
        for account in customer.get("accounts") or []
        if isinstance(account, dict)
    ]
    return {"customer_id": customer_id, "accounts": accounts}, None
