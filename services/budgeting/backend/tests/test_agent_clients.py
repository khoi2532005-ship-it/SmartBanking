"""Checks for the Release 1 MCP and RAG clients and their routes, and the AI-Mode switch.

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


# ---------------------------------------------------------------------------
# Non-object JSON bodies - a caller's mistake is a 400, never a 500
# ---------------------------------------------------------------------------

NON_OBJECT_BODIES = ("[1]", '"hi"', "42", "[]")
BODY_ROUTES = (
    ("post", "/api/mcp/tool"),
    ("post", "/api/rag/query"),
    ("post", "/api/budgets"),
    ("put", "/api/budgets/1"),
    ("post", "/api/budgets/insight"),
)


def test_non_object_json_bodies_are_rejected_with_400():
    """`[1]`, `"hi"` and `42` used to reach `data.get` and raise (review finding
    on PR #41). Every POST/PUT route now goes through routes.json_object()."""
    with _env(MCP_ENABLED="false", RAG_ENABLED="false"):
        c = _client()
        for method, path in BODY_ROUTES:
            for body in NON_OBJECT_BODIES:
                r = getattr(c, method)(path, data=body, content_type="application/json")
                assert r.status_code == 400, (method, path, body, r.status_code)
                assert r.get_json()["error"] == "JSON object body required", (path, body)


def test_null_or_missing_body_falls_back_to_defaults():
    """`null` and an absent body mean {}: the route reports what it needs, or
    that the integration is disabled - it never raises."""
    with _env(MCP_ENABLED="false", RAG_ENABLED="false"):
        c = _client()
        assert c.post("/api/rag/query", data="null", content_type="application/json").status_code == 400
        assert c.post("/api/rag/query").status_code == 400
        assert c.post("/api/budgets", data="null", content_type="application/json").status_code == 400
        assert c.post("/api/mcp/tool", data="null", content_type="application/json").status_code == 503
        assert c.post("/api/mcp/tool").status_code == 503


# ---------------------------------------------------------------------------
# Release 1 panels - status fragments and the frontend wiring
# ---------------------------------------------------------------------------

FRONTEND_TAB = BASE_DIR.parent / "frontend" / "tabs" / "ai-mode.html"      # Release 2: the AI panels moved to the AI Mode tab


def test_status_fragments_render_the_inactive_state_without_network():
    with _env(MCP_ENABLED="false", RAG_ENABLED="false"):
        c = _client()
        for path in ("/ui/mcp/status", "/ui/rag/status"):
            r = c.get(path)
            assert r.status_code == 200, (path, r.status_code)
            assert b"Inactive" in r.data and b"_ENABLED=false" in r.data, path


def test_status_fragments_render_unreachable_with_the_start_hint():
    with _env(MCP_ENABLED="true", RAG_ENABLED="true", MCP_SERVER_URL=DEAD_PORT_URL, RAG_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.get("/ui/mcp/status")
        assert r.status_code == 200 and b"Unreachable" in r.data
        assert b"python -m mcp_server.server" in r.data
        r = c.get("/ui/rag/status")
        assert r.status_code == 200 and b"Unreachable" in r.data
        assert b"python -m rag_server.server" in r.data


def test_rag_question_length_is_capped_before_any_call():
    too_long = "x" * (rag_client.MAX_QUERY_CHARS + 1)
    with _env(RAG_ENABLED="true", RAG_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/ui/rag/query", data={"query": too_long})
        assert r.status_code == 200 and b"1000 characters" in r.data
        r = c.post("/api/rag/query", json={"query": too_long})
        assert r.status_code == 400 and "1000" in r.get_json()["error"]


GROUNDED_ANSWER = {
    "query": "What does NEAR_LIMIT mean for a budget?",
    "answer": "A budget is NEAR_LIMIT when spending reaches 80% of the monthly limit "
              "without exceeding it [budgeting-feature#002].",
    "citations": [{"chunk_id": "budgeting-feature#002", "source_id": "budgeting-feature",
                   "title": "Budgeting & Spending Insights", "authority_tier": 1}],
    "confidence_category": "High",
    "insufficient_context": False,
    "retrieval_summary": {"k": 5, "retrieved_count": 5, "relevant_count": 3,
                          "retrieval_mode": "hybrid", "top_chunk": "budgeting-feature#002"},
    "generation": {"model": "gemini / test"},
}


def test_rag_fragment_renders_grounded_answer_with_badge_and_citation_chips():
    """The grounded state: confidence badge from the evidence, the [chunk#nnn]
    marker in the prose turned into a chip, and the citation list."""
    original = rag_client._request
    rag_client._request = lambda method, path, body=None: (200, dict(GROUNDED_ANSWER))
    try:
        with _env(RAG_ENABLED="true"):
            c = _client()
            r = c.post("/ui/rag/query", data={"query": GROUNDED_ANSWER["query"]})
    finally:
        rag_client._request = original
    assert r.status_code == 200
    page = r.data.decode()
    assert 'class="insight-card rag-answer"' in page and "rag-insufficient" not in page
    assert 'badge-ok">Confidence: High' in page
    assert page.count('<span class="chip">budgeting-feature#002</span>') == 2   # prose marker + citation list
    assert "Citations (1)" in page and "tier 1" in page
    assert "[budgeting-feature#002]" not in page                                # marker replaced, not duplicated
    assert "retrieved 5" in page and "relevant 3" in page and "mode hybrid" in page


def test_rag_status_fragment_escapes_server_supplied_values():
    """Counts and mode come from the RAG server's JSON; render them as text, never markup."""
    original = rag_client.status
    rag_client.status = lambda: {"enabled": True, "url": "http://x:8200", "reachable": True,
                                 "index": {"chunks": "<b>65</b>", "sources": 9, "retrieval_mode": "<i>hybrid</i>"},
                                 "model": "<script>m</script>"}
    try:
        with _env(RAG_ENABLED="true"):
            page = _client().get("/ui/rag/status").get_data(as_text=True)
    finally:
        rag_client.status = original
    assert "<b>" not in page and "<i>" not in page and "<script>" not in page
    assert "&lt;b&gt;65&lt;/b&gt;" in page and "&lt;i&gt;hybrid&lt;/i&gt;" in page


def test_frontend_tab_wires_every_release_1_fragment():
    """The panels use only fragment endpoints that exist on this backend."""
    html = FRONTEND_TAB.read_text(encoding="utf-8")
    for needle in (
        'hx-get="/ui/mcp/status"', 'hx-post="/ui/mcp/tool"', 'hx-get="/ui/mcp/tools"',
        'hx-get="/ui/rag/status"', 'hx-post="/ui/rag/query"',
        'id="mcp-panel"', 'id="mcp-tools-panel"', 'id="rag-panel"',
        'name="query"', 'hx-include="#period-form"',
    ):
        assert needle in html, needle

    from app import app
    ui_rules = {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/ui/")}
    for path in ("/ui/mcp/status", "/ui/mcp/tool", "/ui/mcp/tools", "/ui/rag/status", "/ui/rag/query"):
        assert path in ui_rules, path


# ---------------------------------------------------------------------------
# AI-Mode switch (Release 2): AI_MODE_ENABLED=false stops every model call
# ---------------------------------------------------------------------------

class _no_backing_calls:
    """Record any database, Transactions or model call, so a check can prove none was made."""

    def __enter__(self):
        from services import database_api, insight_service, transactions_client
        self.calls = []
        self.targets = [(database_api, "search_budgets"), (database_api, "get_budget_response"),
                        (transactions_client, "spend_by_category"), (insight_service, "create_chat_completion")]
        self.originals = [getattr(module, name) for module, name in self.targets]
        for module, name in self.targets:
            setattr(module, name, self._recorder(name))
        return self

    def _recorder(self, name):
        def called(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"{name} was called")
        return called

    def __exit__(self, *exc):
        for (module, name), original in zip(self.targets, self.originals):
            setattr(module, name, original)


def test_ai_mode_is_on_unless_switched_off():
    from services import llm_client
    saved = os.environ.pop("AI_MODE_ENABLED", None)
    try:
        assert llm_client.enabled(), "unset means on, as for MCP_ENABLED"
    finally:
        if saved is not None:
            os.environ["AI_MODE_ENABLED"] = saved
    for off in ("false", "False", "0", "off", "no"):
        with _env(AI_MODE_ENABLED=off):
            assert not llm_client.enabled(), off


def test_ai_mode_off_refuses_the_model_call_itself():
    from services import llm_client
    # No key is set up on purpose: the switch must refuse before any client or key is touched.
    with _env(AI_MODE_ENABLED="false", LLM_PROVIDER="gemini"):
        exc = _raises(lambda: llm_client.create_chat_completion([{"role": "user", "content": "hi"}]),
                      llm_client.AIModeDisabled)
        assert "AI_MODE_ENABLED=false" in str(exc)


def test_ai_mode_off_answers_503_before_any_database_or_model_call():
    with _env(AI_MODE_ENABLED="false"), _no_backing_calls() as stub:
        c = _client()
        r = c.post("/api/budgets/insight", json={"customer_id": 1, "month": 9, "year": 2026})
        assert r.status_code == 503, r.status_code
        assert r.get_json()["disabled"] is True and "AI_MODE_ENABLED=false" in r.get_json()["error"]
        r = c.post("/api/budgets/1/explain")
        assert r.status_code == 503 and r.get_json()["disabled"] is True
        assert stub.calls == [], stub.calls


def test_ai_mode_off_fragments_warn_and_the_status_line_says_inactive():
    with _env(AI_MODE_ENABLED="false"), _no_backing_calls() as stub:
        c = _client()
        for path in ("/ui/insight", "/ui/budgets/1/explain"):
            r = c.post(path, data={"customer_id": "1", "month": "9", "year": "2026"})
            assert r.status_code == 200 and b"alert-warn" in r.data, (path, r.data[:200])
            assert b"AI_MODE_ENABLED=false" in r.data, path
        r = c.get("/ui/ai/status")
        assert r.status_code == 200 and b"Inactive" in r.data and b"AI_MODE_ENABLED=false" in r.data
        assert stub.calls == [], stub.calls


def test_ai_mode_on_status_line_names_the_model_without_calling_it():
    with _env(AI_MODE_ENABLED="true", LLM_PROVIDER="gemini", GEMINI_MODEL="gemini-flash-lite-latest"), \
            _no_backing_calls() as stub:
        r = _client().get("/ui/ai/status")
        assert r.status_code == 200 and b"Enabled" in r.data, r.data
        assert b"gemini / gemini-flash-lite-latest" in r.data
        assert stub.calls == [], stub.calls


def test_health_and_agents_status_report_ai_mode():
    with _env(AI_MODE_ENABLED="false", LLM_PROVIDER="gemini", MCP_ENABLED="false", RAG_ENABLED="false",
              MULTI_AGENT_ENABLED="false"):
        c = _client()
        assert c.get("/api/health").get_json()["ai_mode"] == {"enabled": False, "provider": "gemini"}
        status = c.get("/api/agents/status").get_json()["ai_mode"]
        assert status["enabled"] is False and status["provider"] == "gemini" and status["model"], status
    with _env(AI_MODE_ENABLED="true", LLM_PROVIDER="gemini"):
        assert _client().get("/api/health").get_json()["ai_mode"]["enabled"] is True


def test_insight_card_names_the_provider_in_use():
    """The card used to say "Generated by Ollama" whichever provider answered."""
    from routes import ui
    for name, shown in (("gemini", "Gemini"), ("ollama", "Ollama")):
        with _env(LLM_PROVIDER=name):
            html = ui._insight_card("Title", "Body", "some-model", "mock")
            assert f"Generated by {shown} running" in html, html


def test_every_target_of_a_budget_row_exists_on_the_normal_tab():
    """Since the tab split the rows' Explain button targeted a panel only the AI Mode tab had,
    so Explain did nothing on the Normal tab, where the rows are."""
    from routes import ui
    row = ui._budget_row({"budget_id": 1, "category": "Groceries", "monthly_limit": 800.0, "spent": 645.0,
                          "remaining": 155.0, "percent_used": 80.6, "status": "NEAR_LIMIT", "over_budget": False,
                          "over_by": 0.0})
    normal_tab = (BASE_DIR.parent / "frontend" / "tabs" / "budgets.html").read_text(encoding="utf-8")
    import re
    targets = set(re.findall(r'hx-(?:target|indicator)="#([\w-]+)"', row))
    assert targets >= {"insight-panel", "insight-spinner", "budget-list"}, targets
    for target in targets:
        assert f'id="{target}"' in normal_tab, f"#{target} is not on the Normal tab"


def _borrowed_targets(html):
    """Each htmx request element with no hx-target of its own inside one that has an
    hx-target: htmx swaps its answer into that enclosing target instead of itself."""
    from html.parser import HTMLParser

    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    open_elements, borrowed = [], []

    class Walker(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if not {"hx-get", "hx-post", "hx-put", "hx-delete"}.isdisjoint(attrs) and "hx-target" not in attrs:
                enclosing = next((a["hx-target"] for _, a in reversed(open_elements) if "hx-target" in a), None)
                if enclosing:
                    borrowed.append(f'<{tag} id="{attrs.get("id", "")}"> -> {enclosing}')
            if tag not in void:
                open_elements.append((tag, attrs))

        def handle_endtag(self, tag):
            names = [name for name, _ in open_elements]
            if tag in names:
                del open_elements[len(names) - 1 - names[::-1].index(tag):]

    Walker().feed(html)
    return borrowed


def test_no_htmx_request_on_a_tab_takes_its_target_from_an_enclosing_element():
    """The create form's category select took the form's hx-target, #budget-list: its options
    went into the budget list, the select stayed on "Loading categories..." and no budget could
    be created from the page."""
    assert _borrowed_targets('<form hx-target="#x"><select hx-get="/a"></select></form>') == ['<select id=""> -> #x']
    for tab in ("budgets.html", "ai-mode.html"):
        borrowed = _borrowed_targets((BASE_DIR.parent / "frontend" / "tabs" / tab).read_text(encoding="utf-8"))
        assert borrowed == [], f"{tab}: {borrowed}"


def test_ai_insight_card_has_its_status_line():
    html = FRONTEND_TAB.read_text(encoding="utf-8")
    assert 'id="ai-status"' in html and html.count('hx-get="/ui/ai/status"') == 2, "status line and Re-check"
    from app import app
    assert "/ui/ai/status" in {r.rule for r in app.url_map.iter_rules()}


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
