"""Post-commit endpoint tests for transactions microservice (Student 5)."""

import json
import os
import pytest
import requests

API_URL = os.getenv("TRANSACTIONS_API_URL", "http://localhost:5005").rstrip("/")
TIMEOUT = 10
_shared = {}


def _record(record_property, desc: str, ok: bool):
    record_property("check", json.dumps({"check": desc, "ok": ok}))
    assert ok, desc


@pytest.mark.endpoint("GET", "/api/health")
def test_service_health(record_property):
    response = requests.get(f"{API_URL}/api/health", timeout=TIMEOUT)
    _record(record_property, "the health endpoint answers 200", response.status_code == 200)

    data = response.json()
    _record(
        record_property,
        "the service identifies itself as transactions-service",
        data.get("service") == "transactions-service",
    )
    _record(
        record_property,
        "the service status is running",
        data.get("status") == "running",
    )


@pytest.mark.endpoint("GET", "/api/transactions")
def test_transactions_list(record_property):
    response = requests.get(f"{API_URL}/api/transactions", timeout=TIMEOUT)
    _record(record_property, "the transactions endpoint answers 200", response.status_code == 200)

    txs = response.json()
    _record(
        record_property,
        "the response contains at least one transaction",
        isinstance(txs, list) and len(txs) > 0,
    )
    has_fields = all(
        {"transaction_id", "account_id", "amount", "date"} <= set(tx) for tx in txs[:5]
    )
    _record(
        record_property,
        "every transaction has transaction_id, account_id, amount, and date",
        has_fields,
    )


@pytest.mark.endpoint("POST", "/api/transactions")
def test_create_transaction(record_property):
    payload = {
        "account_id": 1,
        "amount": 75.50,
        "currency": "AUD",
        "type": "Deposit",
        "category": "Income",
        "description": "Post-commit test deposit",
        "date": "2026-10-26",
    }
    response = requests.post(f"{API_URL}/api/transactions", json=payload, timeout=TIMEOUT)
    _record(record_property, "the create transaction endpoint answers 201", response.status_code == 201)

    data = response.json()
    tx_id = data.get("transaction_id")
    _shared["created_id"] = tx_id
    _record(
        record_property,
        "the response contains a positive transaction_id",
        isinstance(tx_id, int) and tx_id > 0,
    )
    _record(
        record_property,
        "the response confirms transaction creation",
        "created" in data.get("message", "").lower(),
    )


@pytest.mark.endpoint("GET", "/api/transactions/{transaction_id}")
def test_transaction_by_id(record_property):
    tx_id = _shared.get("created_id")
    if not tx_id:
        txs = requests.get(f"{API_URL}/api/transactions", timeout=TIMEOUT).json()
        tx_id = txs[0]["transaction_id"]

    response = requests.get(f"{API_URL}/api/transactions/{tx_id}", timeout=TIMEOUT)
    _record(record_property, "the transaction-by-id endpoint answers 200", response.status_code == 200)

    data = response.json()
    _record(
        record_property,
        "the response transaction_id matches the requested id",
        data.get("transaction_id") == tx_id,
    )
    _record(
        record_property,
        "the response contains account_id and amount",
        "account_id" in data and "amount" in data,
    )


@pytest.mark.endpoint("DELETE", "/api/transactions/{transaction_id}")
def test_delete_transaction(record_property):
    tx_id = _shared.get("created_id")
    if not tx_id:
        # Create a temporary transaction to delete
        payload = {
            "account_id": 1,
            "amount": 10.0,
            "currency": "AUD",
            "type": "Withdrawal",
            "category": "Other",
            "description": "Temp deletion test",
            "date": "2026-10-26",
        }
        create_res = requests.post(f"{API_URL}/api/transactions", json=payload, timeout=TIMEOUT)
        tx_id = create_res.json().get("transaction_id")

    response = requests.delete(f"{API_URL}/api/transactions/{tx_id}", timeout=TIMEOUT)
    _record(record_property, "the delete transaction endpoint answers 200", response.status_code == 200)

    data = response.json()
    _record(
        record_property,
        "the response contains deleted id matching the transaction",
        data.get("deleted") == tx_id,
    )
