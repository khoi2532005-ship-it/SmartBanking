"""Unit tests for the Loans & Credit MCP / RAG backend integration.

No running services, no shared MCP/RAG server, no LLM: the routes are driven
through the Flask test client with MCP_SERVER_URL / RAG_SERVICE_URL pointed at
a port nothing listens on (connection refused), so the "dependency down" paths
are exercised for real. Skipped where flask is not installed, in line with the
other test modules.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

LOANS_BACKEND = Path(__file__).resolve().parent.parent / "services" / "loans" / "backend"
sys.path.insert(0, str(LOANS_BACKEND))

pytest.importorskip("flask")
pytest.importorskip("requests")

# Pointed at unused ports before imports read the env, so the "shared server
# down" branches fail immediately instead of touching a real service.
os.environ["MCP_ENABLED"] = "true"
os.environ["RAG_ENABLED"] = "true"
os.environ["MCP_SERVER_URL"] = "http://127.0.0.1:9/mcp"
os.environ["RAG_SERVICE_URL"] = "http://127.0.0.1:9"

from app import app  # noqa: E402


@pytest.fixture()
def client():
    with app.test_client() as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# MCP Mode
# ---------------------------------------------------------------------------

def test_mcp_route_respects_the_per_request_mode_header(client):
    response = client.post(
        "/api/mcp/loans-list",
        json={"customer_id": 1},
        headers={"X-MCP-Mode": "off"},
    )
    assert response.status_code == 403
    assert response.get_json()["status"] == "error"


def test_mcp_route_rejects_a_non_integer_customer_id(client):
    for bad in (0, -1, "abc", "1.5"):
        response = client.post("/api/mcp/loans-list", json={"customer_id": bad})
        assert response.status_code == 400
        assert "customer_id" in response.get_json()["error"]


def test_mcp_tool_call_when_shared_server_is_down_is_a_readable_503(client):
    response = client.post("/api/mcp/loans-list", json={"customer_id": 1})
    assert response.status_code == 503
    assert "shared MCP server" in response.get_json()["error"]
    assert "loans_list" not in response.get_json()  # never a fabricated result


def test_mcp_tools_registry_lists_the_loans_tool(client):
    response = client.get("/api/mcp/tools")
    assert response.status_code == 200
    names = [tool["name"] for tool in response.get_json()["tools"]]
    assert "loans_list" in names


def test_mcp_disabled_env_var_returns_403_even_with_the_header_on(client, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "false")
    response = client.post("/api/mcp/loans-list", json={"customer_id": 1})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# RAG Mode
# ---------------------------------------------------------------------------

def test_rag_route_respects_the_per_request_mode_header(client):
    response = client.post(
        "/api/rag/answer",
        json={"query": "what is a loan"},
        headers={"X-RAG-Mode": "off"},
    )
    assert response.status_code == 403
    assert response.get_json()["status"] == "error"


def test_rag_route_requires_a_query(client):
    response = client.post("/api/rag/retrieve", json={"k": 5})
    assert response.status_code == 400
    assert response.get_json()["error"] == "query is required"


def test_rag_call_when_shared_server_is_down_is_a_readable_503(client):
    response = client.post("/api/rag/answer", json={"query": "what is a loan"})
    assert response.status_code == 503
    assert "shared RAG server" in response.get_json()["error"]


def test_rag_disabled_env_var_returns_403_even_with_the_header_on(client, monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    response = client.post("/api/rag/refresh", json={})
    assert response.status_code == 403