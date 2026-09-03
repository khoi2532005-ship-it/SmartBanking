import os

import requests


DATABASE_SERVICE_URL = os.getenv("DATABASE_SERVICE_URL", "http://localhost:5002")
TIMEOUT = 5


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Loan applications
# ---------------------------------------------------------------------------

def search_loans(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/loans",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_loan_response(loan_id):
    return requests.get(f"{DATABASE_SERVICE_URL}/loans/{loan_id}", timeout=TIMEOUT)


def get_loan(loan_id):
    response = get_loan_response(loan_id)
    response.raise_for_status()
    return response.json()


def create_loan(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/loans", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def update_loan(loan_id, payload):
    response = requests.put(
        f"{DATABASE_SERVICE_URL}/loans/{loan_id}", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def delete_loan(loan_id):
    response = requests.delete(
        f"{DATABASE_SERVICE_URL}/loans/{loan_id}", timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Repayments
# ---------------------------------------------------------------------------

def search_repayments(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/repayments",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_repayment(repayment_id):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/repayments/{repayment_id}", timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def create_repayments(items):
    created = []
    for item in items:
        response = requests.post(
            f"{DATABASE_SERVICE_URL}/repayments", json=item, timeout=TIMEOUT
        )
        response.raise_for_status()
        created.append(response.json())
    return created


def update_repayment(repayment_id, payload):
    response = requests.put(
        f"{DATABASE_SERVICE_URL}/repayments/{repayment_id}", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def delete_repayment(repayment_id):
    response = requests.delete(
        f"{DATABASE_SERVICE_URL}/repayments/{repayment_id}", timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()
