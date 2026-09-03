import os

import requests


DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://localhost:5011")
TIMEOUT = 5


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def search_customers(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/customers",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_customer_response(customer_id):
    return requests.get(f"{DATABASE_SERVICE_URL}/customers/{customer_id}", timeout=TIMEOUT)


def get_customer(customer_id):
    response = get_customer_response(customer_id)
    response.raise_for_status()
    return response.json()


def create_customer(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/customers", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def update_customer(customer_id, payload):
    response = requests.put(
        f"{DATABASE_SERVICE_URL}/customers/{customer_id}", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def delete_customer(customer_id):
    response = requests.delete(
        f"{DATABASE_SERVICE_URL}/customers/{customer_id}", timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def search_accounts(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/accounts",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_account_response(account_id):
    return requests.get(f"{DATABASE_SERVICE_URL}/accounts/{account_id}", timeout=TIMEOUT)


def get_account(account_id):
    response = get_account_response(account_id)
    response.raise_for_status()
    return response.json()


def create_account(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/accounts", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def update_account(account_id, payload):
    response = requests.put(
        f"{DATABASE_SERVICE_URL}/accounts/{account_id}", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def delete_account(account_id):
    response = requests.delete(
        f"{DATABASE_SERVICE_URL}/accounts/{account_id}", timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# AI summaries
# ---------------------------------------------------------------------------

def create_ai_summary(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/ai-summaries", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def search_ai_summaries(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/ai-summaries",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()
