"""Checks for the Release 1 MCP and RAG clients and their routes.

No shared server is needed: the disabled and unreachable paths are exercised
for real (an env flag, and a port nothing listens on), and the parsing and
route logic is driven with stubbed transport. Same plain-assert runner as
test_budget_logic so CI needs no test framework. Run from
services/budgeting/backend:

    python -m tests.test_agent_clients
"""

from pathlib import Path
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services import mcp_client, rag_client  # noqa: E402

DEAD_PORT_URL = "http://127.0.0.1:9"     # discard port: connection refused everywhere


class _env:
    """Temporarily set environment variables."""

    def __init__(self, **values):
        self.values = values
        self.saved = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class _StubResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


# ---------------------------------------------------------------------------
# Disabled flag - the integration is retained but inactive (CI configuration)
# ---------------------------------------------------------------------------

def test_mcp_disabled_flag_short_circuits_before_any_network_call():
    with _env(MCP_ENABLED="false", MCP_SERVER_URL=DEAD_PORT_URL):
        assert mcp_client.enabled() is False
        exc = _raises(lambda: mcp_client.call_tool("budgeting_summary", {}), mcp_client.MCPDisabled)
        assert "MCP_ENABLED=false" in str(exc)
        assert mcp_client.status()["enabled"] is False


def test_rag_disabled_flag_short_circuits_before_any_network_call():
    with _env(RAG_ENABLED="false", RAG_SERVER_URL=DEAD_PORT_URL):
        assert rag_client.enabled() is False
        exc = _raises(lambda: rag_client.query("anything"), rag_client.RAGDisabled)
        assert "RAG_ENABLED=false" in str(exc)
        assert rag_client.status()["enabled"] is False


# ---------------------------------------------------------------------------
# Unreachable server - one readable sentence that says how to start it
# ---------------------------------------------------------------------------

def test_mcp_unreachable_is_a_readable_message():
    with _env(MCP_ENABLED="true", MCP_SERVER_URL=DEAD_PORT_URL):
        exc = _raises(lambda: mcp_client.list_tools(), mcp_client.MCPUnreachable)
        assert "python -m mcp_server.server" in str(exc), exc
        status = mcp_client.status()
        assert status["reachable"] is False and status["error"]


def test_rag_unreachable_is_a_readable_message():
    with _env(RAG_ENABLED="true", RAG_SERVER_URL=DEAD_PORT_URL):
        exc = _raises(lambda: rag_client.query("anything"), rag_client.RAGUnreachable)
        assert "python -m rag_server.server" in str(exc), exc
        assert rag_client.status()["reachable"] is False


# ---------------------------------------------------------------------------
# MCP result semantics
# ---------------------------------------------------------------------------

def test_parse_tool_result_keeps_structured_content_on_success():
    result = mcp_client._parse_tool_result("budgeting_summary", {"customer_id": 1}, {
        "isError": False,
        "content": [{"type": "text", "text": '{"budget_count": 7}'}],
        "structuredContent": {"budget_count": 7, "totals": {"total_spent": 10.0}},
    })
    assert result.is_error is False
    assert result.structured == {"budget_count": 7, "totals": {"total_spent": 10.0}}
    assert result.tool == "budgeting_summary"


def test_parse_tool_result_maps_iserror_to_text_and_no_structured():
    result = mcp_client._parse_tool_result("budgeting_summary", {"month": 13}, {
        "isError": True,
        "content": [{"type": "text", "text": "Error executing tool budgeting_summary: month must be between 1 and 12, got 13"}],
    })
    assert result.is_error is True
    assert result.structured is None
    assert "month" in result.text


def test_jsonrpc_error_becomes_protocol_error(monkeypatch=None):
    original = mcp_client.requests.post
    mcp_client.requests.post = lambda *a, **k: _StubResponse(
        200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid request parameters"}}
    )
    try:
        with _env(MCP_ENABLED="true", MCP_SERVER_URL="http://stub"):
            exc = _raises(lambda: mcp_client.list_tools(), mcp_client.MCPProtocolError)
            assert "-32602" in str(exc)
    finally:
        mcp_client.requests.post = original


def test_http_error_from_mcp_server_becomes_protocol_error():
    original = mcp_client.requests.post
    mcp_client.requests.post = lambda *a, **k: _StubResponse(406, "Not Acceptable")
    try:
        with _env(MCP_ENABLED="true", MCP_SERVER_URL="http://stub"):
            exc = _raises(lambda: mcp_client.list_tools(), mcp_client.MCPProtocolError)
            assert "406" in str(exc)
    finally:
        mcp_client.requests.post = original


# ---------------------------------------------------------------------------
# RAG contract validation
# ---------------------------------------------------------------------------

GROUNDED = {
    "answer": "NEAR_LIMIT means 80 to 100 percent used [budgeting-feature#003].",
    "citations": [{"chunk_id": "budgeting-feature#003", "source_id": "budgeting-feature",
                   "title": "Budgeting", "authority_tier": 1}],
    "confidence_category": "Medium",
    "retrieval_summary": {"k": 5, "retrieved_count": 5, "relevant_count": 2, "top_chunk": "budgeting-feature#003"},
    "insufficient_context": False,
}

INSUFFICIENT = {
    "answer": "Insufficient context: the approved SmartBank documents do not contain enough information to answer this question.",
    "citations": [],
    "confidence_category": "Unknown",
    "retrieval_summary": {"k": 5, "retrieved_count": 5, "relevant_count": 0, "top_chunk": "x#001"},
    "insufficient_context": True,
}


def test_contract_accepts_grounded_and_insufficient_shapes():
    assert rag_client._validate_contract(GROUNDED) is GROUNDED
    assert rag_client._validate_contract(INSUFFICIENT) is INSUFFICIENT


def test_contract_rejects_missing_fields_and_bad_confidence():
    broken = dict(GROUNDED)
    del broken["citations"]
    exc = _raises(lambda: rag_client._validate_contract(broken), rag_client.RAGError)
    assert exc.status == 502 and "citations" in str(exc)

    bad = dict(GROUNDED, confidence_category="Certain")
    exc = _raises(lambda: rag_client._validate_contract(bad), rag_client.RAGError)
    assert "confidence" in str(exc)

    contradictory = dict(INSUFFICIENT, citations=GROUNDED["citations"])
    _raises(lambda: rag_client._validate_contract(contradictory), rag_client.RAGError)


def test_query_relays_server_error_status_and_evidence():
    original = rag_client.requests.request
    rag_client.requests.request = lambda *a, **k: _StubResponse(
        503, {"error": "AI provider unavailable: GEMINI_API_KEY is not set",
              "retrieval_summary": {"retrieved_count": 5}, "evidence": []}
    )
    try:
        with _env(RAG_ENABLED="true", RAG_SERVER_URL="http://stub"):
            exc = _raises(lambda: rag_client.query("q"), rag_client.RAGError)
            assert exc.status == 503
            assert exc.payload["retrieval_summary"]["retrieved_count"] == 5
    finally:
        rag_client.requests.request = original


def test_query_requires_a_question():
    exc = _raises(lambda: rag_client.query("   "), rag_client.RAGError)
    assert exc.status == 400


# ---------------------------------------------------------------------------
# Routes - through the Flask test client, with the integrations disabled
# ---------------------------------------------------------------------------

def _client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_routes_report_disabled_integrations_as_503_and_health_stays_200():
    with _env(MCP_ENABLED="false", RAG_ENABLED="false"):
        c = _client()
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.get_json()["mcp"]["enabled"] is False and r.get_json()["rag"]["enabled"] is False

        r = c.post("/api/mcp/tool", json={"customer_id": 1, "month": 9, "year": 2026})
        assert r.status_code == 503 and r.get_json()["disabled"] is True

        r = c.post("/api/rag/query", json={"query": "What does NEAR_LIMIT mean?"})
        assert r.status_code == 503 and r.get_json()["disabled"] is True

        r = c.get("/api/agents/status")
        assert r.status_code == 200
        assert r.get_json()["mcp"]["enabled"] is False

        # HTMX fragments answer 200 with an inactive-state alert, never a broken swap.
        r = c.post("/ui/rag/query", data={"query": "anything"})
        assert r.status_code == 200 and b"disabled" in r.data
        r = c.post("/ui/mcp/tool", data={"customer_id": "1", "month": "9", "year": "2026"})
        assert r.status_code == 200 and b"disabled" in r.data


def test_routes_validate_input_before_calling_out():
    with _env(MCP_ENABLED="true", RAG_ENABLED="true", MCP_SERVER_URL=DEAD_PORT_URL, RAG_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/api/mcp/tool", json={"tool": "drop_all_tables"})
        assert r.status_code == 400 and "allowed_tools" in r.get_json()

        r = c.post("/api/rag/query", json={})
        assert r.status_code == 400

        r = c.post("/api/rag/query", json={"query": "x", "k": "many"})
        assert r.status_code == 400

        # Unreachable servers surface as 503 with the start hint, not a 500.
        r = c.post("/api/mcp/tool", json={})
        assert r.status_code == 503 and "python -m mcp_server.server" in r.get_json()["error"]
        r = c.post("/api/rag/query", json={"query": "x"})
        assert r.status_code == 503 and "python -m rag_server.server" in r.get_json()["error"]


def _run():
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failures = []
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures.append(name)
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures.append(name)
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
