"""Only the fraud tabs may call fraud-service from a browser: the page on port
3003 of the same host this API answers on, plus FRAUD_FRONTEND_ORIGINS."""

import pytest

from app import create_app
from services import database_api


def preflight(client, origin, host="localhost:5003"):
    return client.options("/api/agents/workflow", base_url=f"http://{host}", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})


@pytest.mark.parametrize("host, origin, allowed", [
    ("localhost:5003", "http://localhost:3003", True),       # the fraud tabs, also when the home page frames them
    ("20.211.5.9:5003", "http://20.211.5.9:3003", True),     # the same tabs on the demo VM
    ("localhost:5003", "http://evil.example:3003", False),   # another host's page on the tab's port
    ("localhost:5003", "http://localhost:3004", False),      # another feature's page
    ("localhost:5003", "https://evil.example", False),
])
def test_only_the_fraud_tabs_may_call_the_api(client, host, origin, allowed):
    r = preflight(client, origin, host)
    assert (r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == origin) is allowed


def test_a_foreign_page_is_refused_before_any_route_runs(client, monkeypatch):
    # A plain GET needs no preflight, so the refusal has to happen server-side.
    def never(*args, **kwargs):
        raise AssertionError("the route ran for a foreign page")

    monkeypatch.setattr(database_api, "search_alerts", never)
    r = client.get("/api/alerts", base_url="http://localhost:5003", headers={"Origin": "http://evil.example:3003"})
    assert r.status_code == 403


def test_more_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("FRAUD_FRONTEND_ORIGINS", "https://fraud.example.net, http://localhost:8080")
    client = create_app().test_client()
    for origin in ("https://fraud.example.net", "http://localhost:8080"):
        r = preflight(client, origin)
        assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == origin


def test_an_extra_origin_may_end_in_a_slash(monkeypatch):
    # Copied from the address bar; browsers send the Origin header without it.
    monkeypatch.setenv("FRAUD_FRONTEND_ORIGINS", "https://fraud.example.net/")
    r = preflight(create_app().test_client(), "https://fraud.example.net")
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "https://fraud.example.net"
