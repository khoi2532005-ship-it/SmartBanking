import os

import requests


DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://localhost:5015")
ACCOUNTS_SERVICE_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:5001")
TIMEOUT = 10


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


def search_customers(filters=None):
    try:
        response = requests.get(
            f"{ACCOUNTS_SERVICE_URL}/api/customers",
            params=_params(filters),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def search_accounts(filters=None):
    try:
        response = requests.get(
            f"{ACCOUNTS_SERVICE_URL}/api/accounts",
            params=_params(filters),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def get_account_response(account_id):
    return requests.get(f"{ACCOUNTS_SERVICE_URL}/api/accounts/{account_id}", timeout=TIMEOUT)


def search_transactions(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/transactions",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_transaction_response(transaction_id):
    return requests.get(
        f"{DATABASE_SERVICE_URL}/transactions/{transaction_id}",
        timeout=TIMEOUT,
    )


def create_transaction(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/transactions",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def update_transaction(transaction_id, payload):
    response = requests.put(
        f"{DATABASE_SERVICE_URL}/transactions/{transaction_id}",
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def delete_transaction(transaction_id):
    response = requests.delete(
        f"{DATABASE_SERVICE_URL}/transactions/{transaction_id}",
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
