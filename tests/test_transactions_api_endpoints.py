"""Endpoint-level tests for the transactions backend API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TRANSACTIONS_BACKEND = (
    Path(__file__).resolve().parent.parent / "services" / "transactions" / "backend"
)

# Load this backend in isolation so the same pytest process does not leak its
# top-level `routes` / `services` modules into unrelated feature tests.
existing_modules = {
    name: module
    for name, module in list(sys.modules.items())
    if name in {"app", "routes", "services"}
    or name.startswith("app.")
    or name.startswith("routes.")
    or name.startswith("services.")
}
for name in list(existing_modules):
    del sys.modules[name]

sys.path.insert(0, str(TRANSACTIONS_BACKEND))
try:
    import app as transactions_app  # noqa: E402
    from routes import transactions as transactions_routes  # noqa: E402
finally:
    for name in list(sys.modules):
        if name in {"app", "routes", "services"} or name.startswith("app.") or name.startswith("routes.") or name.startswith("services."):
            del sys.modules[name]
    sys.modules.update(existing_modules)

app = transactions_app.app


@pytest.fixture()
def client():
    with app.test_client() as test_client:
        yield test_client


def test_list_transactions_endpoint_returns_db_rows(monkeypatch, client):
    expected = [{"transaction_id": 1, "amount": "12.50", "customer_id": 7}]

    def fake_search_transactions(filters):
        assert filters == {
            "account_id": None,
            "customer_id": "7",
            "type": "debit",
            "category": None,
            "min_amount": None,
            "max_amount": None,
            "date_from": None,
            "date_to": None,
            "q": "coffee",
        }
        return expected

    monkeypatch.setattr(
        transactions_routes.database_api,
        "search_transactions",
        fake_search_transactions,
    )

    response = client.get(
        "/api/transactions",
        query_string={"customer_id": 7, "type": "debit", "q": "coffee"},
    )

    assert response.status_code == 200
    assert response.get_json() == expected


def test_create_transaction_endpoint_reuses_ai_category_and_persists(
    monkeypatch, client
):
    captured = {}

    def fake_create_transaction(payload):
        captured["payload"] = payload
        return {"transaction_id": 99, "message": "Transaction created"}

    def fake_llm(messages, **kwargs):
        assert messages[0]["role"] == "system"
        assert "Transaction description:" in messages[1]["content"]
        return "Groceries"

    monkeypatch.setattr(
        transactions_routes.database_api, "create_transaction", fake_create_transaction
    )
    monkeypatch.setattr(transactions_routes, "create_chat_completion", fake_llm)

    response = client.post(
        "/api/transactions",
        json={
            "account_id": 12,
            "amount": "42.50",
            "currency": "aud",
            "type": "debit",
            "date": "2026-09-09",
            "description": "Weekly supermarket shop",
        },
    )

    assert response.status_code == 201
    assert response.get_json() == {
        "transaction_id": 99,
        "message": "Transaction created",
    }
    assert captured["payload"]["account_id"] == 12
    assert captured["payload"]["amount"] == 42.5
    assert captured["payload"]["currency"] == "AUD"
    assert captured["payload"]["type"] == "debit"
    assert captured["payload"]["category"] == "Groceries"
