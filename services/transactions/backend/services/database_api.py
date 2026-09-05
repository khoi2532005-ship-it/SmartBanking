import os

import requests


DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://localhost:5015")
TIMEOUT = 5


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


def search_customers(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/customers",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def search_accounts(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/accounts",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


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
