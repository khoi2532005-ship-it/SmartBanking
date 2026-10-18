"""Only the fraud tabs (port 3003) may call fraud-service from a browser."""

import pytest

from app import create_app


def preflight(client, origin):
    return client.options("/api/agents/workflow", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})


@pytest.mark.parametrize("origin, allowed", [
    ("http://localhost:3003", True),     # the fraud tabs, also when the home page frames them
    ("http://20.211.5.9:3003", True),    # the same tabs on the demo VM
    ("http://localhost:3004", False),    # another feature's page
    ("https://evil.example", False),
])
def test_only_the_fraud_tabs_may_call_the_api(client, origin, allowed):
    assert (preflight(client, origin).headers.get("Access-Control-Allow-Origin") == origin) is allowed


def test_more_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("FRAUD_FRONTEND_ORIGINS", "https://fraud.example.net, http://localhost:8080")
    client = create_app().test_client()
    for origin in ("https://fraud.example.net", "http://localhost:8080"):
        assert preflight(client, origin).headers.get("Access-Control-Allow-Origin") == origin
