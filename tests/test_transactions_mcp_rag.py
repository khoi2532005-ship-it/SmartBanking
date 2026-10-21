"""Unit tests for the Transactions MCP / RAG backend integration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TRANSACTIONS_BACKEND = Path(__file__).resolve().parent.parent / "services" / "transactions" / "backend"

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
finally:
    for name in list(sys.modules):
        if name in {"app", "routes", "services"} or name.startswith("app.") or name.startswith("routes.") or name.startswith("services."):
            del sys.modules[name]
    sys.modules.update(existing_modules)

pytest.importorskip("flask")
pytest.importorskip("requests")

os.environ["MCP_ENABLED"] = "true"
os.environ["RAG_ENABLED"] = "true"
os.environ["MCP_SERVER_URL"] = "http://127.0.0.1:9/mcp"
os.environ["RAG_SERVER_URL"] = "http://127.0.0.1:9"

app = transactions_app.app


@pytest.fixture()
def client():
    with app.test_client() as test_client:
        yield test_client


def test_transactions_status_reports_shared_integrations(client):
    response = client.get("/api/agents/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert "mcp" in payload
    assert "rag" in payload
    assert payload["mcp"]["enabled"] is True
    assert payload["rag"]["enabled"] is True


def test_transactions_mcp_tool_route_is_available(client):
    response = client.post(
        "/api/mcp/tool",
        json={"tool": "transactions_spending", "arguments": {"customer_id": 1, "month": 9, "year": 2026}},
    )
    assert response.status_code == 503
    body = response.get_json()
    assert "shared MCP server" in body["error"]


def test_transactions_rag_query_route_is_available(client):
    response = client.post("/api/rag/query", json={"query": "what are transactions?"})
    assert response.status_code == 503
    body = response.get_json()
    assert "shared RAG server" in body["error"]
