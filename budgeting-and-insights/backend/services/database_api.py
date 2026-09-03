"""Typed HTTP client for this feature's own database service.

The budgets database service is the exclusive owner of budgeting_and_insights.db.
Nothing outside that service reads the SQLite file directly.
"""

import os

import requests


DATABASE_SERVICE_URL = os.getenv("BUDGET_DB_URL", "http://localhost:5014")
TIMEOUT = 5


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

def search_budgets(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/budgets",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_budget_response(budget_id):
    return requests.get(f"{DATABASE_SERVICE_URL}/budgets/{budget_id}", timeout=TIMEOUT)


def get_budget(budget_id):
    response = get_budget_response(budget_id)
    response.raise_for_status()
    return response.json()


def create_budget(payload):
    return requests.post(
        f"{DATABASE_SERVICE_URL}/budgets", json=payload, timeout=TIMEOUT
    )


def update_budget(budget_id, payload):
    return requests.put(
        f"{DATABASE_SERVICE_URL}/budgets/{budget_id}", json=payload, timeout=TIMEOUT
    )


def delete_budget(budget_id):
    return requests.delete(
        f"{DATABASE_SERVICE_URL}/budgets/{budget_id}", timeout=TIMEOUT
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

def search_categories():
    response = requests.get(f"{DATABASE_SERVICE_URL}/categories", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def create_category(payload):
    return requests.post(
        f"{DATABASE_SERVICE_URL}/categories", json=payload, timeout=TIMEOUT
    )


def update_category(category_id, payload):
    return requests.put(
        f"{DATABASE_SERVICE_URL}/categories/{category_id}",
        json=payload,
        timeout=TIMEOUT,
    )


def delete_category(category_id):
    return requests.delete(
        f"{DATABASE_SERVICE_URL}/categories/{category_id}", timeout=TIMEOUT
    )


# ---------------------------------------------------------------------------
# Budget insights
# ---------------------------------------------------------------------------

def search_insights(filters=None):
    response = requests.get(
        f"{DATABASE_SERVICE_URL}/insights",
        params=_params(filters),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def create_insight(payload):
    response = requests.post(
        f"{DATABASE_SERVICE_URL}/insights", json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def delete_insight(insight_id):
    return requests.delete(
        f"{DATABASE_SERVICE_URL}/insights/{insight_id}", timeout=TIMEOUT
    )
