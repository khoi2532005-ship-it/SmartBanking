"""Checks for the Release 2 Multi-Agent client, its routes and its fragments.

No shared server is needed: the disabled and unreachable paths are exercised
for real (an env flag, and a port nothing listens on), and everything else is
driven through a stubbed transport that answers like the server does. Same
plain-assert runner as test_agent_clients. Run from services/budgeting/backend:

    python -m tests.test_multi_agent_client
"""

from pathlib import Path
import os
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services import multi_agent_client as ma  # noqa: E402

DEAD_PORT_URL = "http://127.0.0.1:9"
HX = {"HX-Request": "true"}              # what HTMX sends; a cross-site form cannot


class _env:
    def __init__(self, **values):
        self.values, self.saved = values, {}

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


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type as exc:
        return exc
    raise AssertionError(f"expected {exc_type.__name__}")


# ---------------------------------------------------------------- a fake server behind _request

WID = "wf_0a1b2c3d"
OLDER_WID = "wf_00000002"
LOANS_WID = "wf_00000001"
STAGES_DONE = [
    {"role": "planner", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 2.1, "fallback": False},
    {"role": "worker", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 1.5, "fallback": False},
    {"role": "reviewer", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 1.8, "fallback": False},
    {"role": "human", "attempt": 1, "status": "running", "model": "human", "duration_seconds": None, "fallback": False},
]
SUMMARY_AWAITING = {"workflow_id": WID, "feature": "budgeting", "state": "awaiting_human_review", "stages": STAGES_DONE,
                    "revisions": 0, "has_plan": True, "has_result": True, "has_review": True, "decision": None,
                    "released": False, "error": "", "created_at": "2026-10-18T01:00:00+00:00", "updated_at": "2026-10-18T01:00:07+00:00"}
REQUEST = "Which categories went over budget in September 2026?"
CONTEXT = {"customer_id": 1, "month": 9, "year": 2026}
FULL_AWAITING = {
    **SUMMARY_AWAITING,
    "request": REQUEST,
    "context": CONTEXT,
    "plan": {"objective": "Find the over-budget categories for 09/2026", "success_criteria": ["Every over-budget category is named"],
             "limitations": [], "meta": {"source": "model", "attempts": 1},
             "tasks": [{"id": "t1", "kind": "api", "title": "Summary", "endpoint": "/api/budgets/summary",
                        "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "totals"},
                       {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "name them", "evidence": "x"}]},
    "result": {"evidence": [{"task_id": "t1", "endpoint": "/api/budgets/summary", "url": "http://localhost:5004/api/budgets/summary",
                             "params": {"customer_id": 1, "month": 9, "year": 2026}, "status": "ok", "http_status": 200,
                             "duration_seconds": 0.02, "summary": {"budget_count": 7}, "error": ""}],
               "findings": [{"task_id": "t2", "statement": "Dining Out is over by 25.2 and Shopping by 74.9.", "evidence": ["t1"]}],
               "answer": "Two categories are over budget: Dining Out by 25.2 and Shopping by 74.9.",
               "gaps": [], "request_only_numbers": [], "meta": {"source": "model", "attempt": 1, "attempts": 1}},
    "review": {"verdict": "accept", "summary": "The findings match the evidence.", "escalated": False, "escalation_reason": "",
               "criteria": [{"index": 1, "met": True, "note": "both named"}], "defects": [],
               "risks": ["Spending source is <mock>"], "revision_notes": [],
               "checks": {"evidence_ok": 1}, "meta": {"source": "model", "attempt": 1}},
    "final_response": None,
}
RESPONSE_ACCEPTED = {"workflow_id": WID, "feature": "budgeting", "decision": "accept", "released": True,
                     "released_at": "2026-10-18T01:01:00+00:00", "decided_by": "budgeting-ui",
                     "answer": FULL_AWAITING["result"]["answer"], "findings": FULL_AWAITING["result"]["findings"],
                     "correction_note": "", "review_verdict": "accept", "review_summary": "ok",
                     "risks": ["Spending source is <mock>"], "gaps": [], "request_only_numbers": [],
                     "evidence_sources": [{"task_id": "t1", "endpoint": "/api/budgets/summary", "url": "http://x", "status": "ok"}],
                     "revisions": 0, "models": ["gemini / g"]}


class FakeServer:
    """Answers like the Multi-Agent Server; records every call."""

    def __init__(self, state="awaiting_human_review"):
        self.state = state
        self.calls = []
        self.decision = None

    def _final(self):
        """The final response the server builds from the decision that was made."""
        kind = self.decision["decision"]
        released = kind != "reject"
        return {**RESPONSE_ACCEPTED, "decision": kind, "released": released, "decided_by": self.decision["by"],
                "correction_note": self.decision["note"], "answer": RESPONSE_ACCEPTED["answer"] if released else None,
                "findings": RESPONSE_ACCEPTED["findings"] if released else [], "released_at": self.decision["decided_at"] if released else None}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/health":
            return 200, {"service": "multi-agent-server", "pipeline": ["planner", "worker", "reviewer", "human"],
                         "pending": 1, "auth": "open", "models": {"planner": "shared AI-Mode model"}}
        if (method, path) == ("POST", "/workflow"):
            return 202, {**SUMMARY_AWAITING, "state": "created", "stages": [], "links": {}}
        if path == f"/workflow/{WID}/status":
            summary = {**SUMMARY_AWAITING, "state": self.state, "decision": self.decision,
                       "released": bool(self.decision and self.decision["decision"] != "reject")}
            if self.state == "failed":
                summary["error"] = "worker: no feature API answered: budgeting service unavailable: connection refused at http://localhost:5004/api/budgets/summary"
            return 200, summary
        if path == f"/workflow/{WID}":
            full = {**FULL_AWAITING, "state": self.state}
            if self.state == "failed":
                full.update(error="worker: no feature API answered: budgeting service unavailable", result=None, review=None)
            if self.decision:
                full.update(decision=self.decision, final_response=self._final())
            return 200, full
        if (method, path) == ("POST", f"/workflow/{WID}/decision"):
            if self.state != "awaiting_human_review":
                return 409, {"error": f"workflow {WID} is {self.state}, not awaiting_human_review", "state": self.state}
            self.state = {"accept": "accepted", "partially_accept": "partially_accepted", "reject": "rejected"}[body["decision"]]
            self.decision = {"decision": body["decision"], "note": body["note"], "by": body["by"], "decided_at": "2026-10-18T01:01:00+00:00"}
            return 200, {**SUMMARY_AWAITING, "state": self.state, "decision": self.decision,
                         "released": body["decision"] != "reject", "final_response": self._final()}
        if path.startswith("/workflows"):
            # the server's listing: every feature's workflows, newest first, narrowed by the query it is sent
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(path).query)
            rows = [
                {**SUMMARY_AWAITING, "workflow_id": LOANS_WID, "feature": "loans", "state": "accepted",
                 "created_at": "2026-10-18T02:00:00+00:00", "request": "List my loans", "context": {"customer_id": 1}},
                {**SUMMARY_AWAITING, "state": self.state, "decision": self.decision, "request": REQUEST, "context": CONTEXT},
                {**SUMMARY_AWAITING, "workflow_id": OLDER_WID, "state": "rejected", "created_at": "2026-10-17T09:00:00+00:00",
                 "request": "Older question", "context": CONTEXT},
            ]
            if query.get("feature"):
                rows = [w for w in rows if w["feature"] == query["feature"][0]]
            if query.get("customer_id"):
                rows = [w for w in rows if w["context"].get("customer_id") == int(query["customer_id"][0])]
            if query.get("limit"):
                rows = rows[:int(query["limit"][0])]
            return 200, rows
        return 404, {"error": f"unknown workflow {path!r}"}


class _stub:
    """Swap the client's transport for a FakeServer for the duration of a test."""

    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.saved = ma._request
        ma._request = self.fake
        return self.fake

    def __exit__(self, *exc):
        ma._request = self.saved


# ---------------------------------------------------------------- disabled and unreachable

def test_disabled_flag_short_circuits_before_any_network_call():
    with _env(MULTI_AGENT_ENABLED="false", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        assert ma.enabled() is False
        exc = _raises(lambda: ma.start("x", 1, 9, 2026), ma.MultiAgentDisabled)
        assert "MULTI_AGENT_ENABLED=false" in str(exc)
        assert ma.status()["enabled"] is False


def test_unreachable_is_a_readable_message_with_the_start_command():
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        exc = _raises(lambda: ma.start("x", 1, 9, 2026), ma.MultiAgentUnreachable)
        assert "python -m multi_agent_server.server" in str(exc), exc
        info = ma.status()
        assert info["reachable"] is False and info["error"]


def test_bearer_token_is_sent_when_configured():
    import requests
    seen = {}

    class R:
        status_code = 200
        def json(self):
            return {"service": "multi-agent-server"}

    def fake_request(method, url, json=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return R()

    saved = requests.request
    requests.request = fake_request
    try:
        with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL="http://host.docker.internal:8300/", MULTI_AGENT_API_TOKEN="s3cret"):  # noqa: S106  # fake token in test fixture only
            ma.health()
            assert seen["url"] == "http://host.docker.internal:8300/health"
            assert seen["headers"] == {"Authorization": "Bearer s3cret"} and seen["timeout"][0] == 2
        with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_API_TOKEN=""):
            ma.health()
            assert seen["headers"] == {}
    finally:
        requests.request = saved


# ---------------------------------------------------------------- client semantics

def test_start_validates_the_request_then_posts_the_context():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        exc = _raises(lambda: ma.start("   ", 1, 9, 2026), ma.MultiAgentError)
        assert exc.status == 400 and "required" in str(exc)
        exc = _raises(lambda: ma.start("x" * (ma.MAX_REQUEST_CHARS + 1), 1, 9, 2026), ma.MultiAgentError)
        assert exc.status == 400 and fake.calls == []                      # nothing left the container
        summary = ma.start("Which categories went over?", "1", "9", "2026")
        assert summary["workflow_id"] == WID and summary["state"] == "created"
        assert fake.calls[-1] == ("POST", "/workflow", {"feature": "budgeting", "request": "Which categories went over?",
                                                        "context": {"customer_id": 1, "month": 9, "year": 2026}})


def test_decide_validates_before_calling_and_relays_the_server_answer():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        assert _raises(lambda: ma.decide(WID, "maybe"), ma.MultiAgentError).status == 400
        assert "needs a note" in str(_raises(lambda: ma.decide(WID, "partially accept"), ma.MultiAgentError))
        assert _raises(lambda: ma.decide(WID, "accept", "x" * 1001), ma.MultiAgentError).status == 400
        assert fake.calls == []
        body = ma.decide(WID, "Partially-Accept", "say the period")
        assert body["state"] == "partially_accepted" and body["final_response"]["correction_note"] == "say the period"
        assert fake.calls[-1][2] == {"decision": "partially_accept", "note": "say the period", "by": "budgeting-ui"}
        exc = _raises(lambda: ma.decide(WID, "reject", "no"), ma.MultiAgentError)
        assert exc.status == 409 and exc.payload["state"] == "partially_accepted"


def test_history_asks_for_this_features_workflows_and_rejects_bad_bodies():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        listing = ma.history()
        assert fake.calls[-1][1] == f"/workflows?feature=budgeting&limit={ma.HISTORY_LIMIT}"   # the server filters and caps
        assert [w["workflow_id"] for w in listing] == [WID, OLDER_WID]                  # budgeting only, newest first
        assert listing[0]["request"] == REQUEST and listing[0]["context"] == CONTEXT
        assert ma.history(customer_id=2) == [] and fake.calls[-1][1].endswith("&customer_id=2")
        assert [w["workflow_id"] for w in ma.history(limit=1)] == [WID]
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (200, [{**SUMMARY_AWAITING, "feature": "loans"}])):
        assert ma.history() == []                                                       # a stray other-feature row is dropped here too
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (200, {"workflows": []})):
        assert _raises(ma.history, ma.MultiAgentError).status == 502
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (200, [1, 2])):
        assert _raises(ma.history, ma.MultiAgentError).status == 502
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (401, {"error": "missing or invalid bearer token"})):
        exc = _raises(ma.history, ma.MultiAgentError)
        assert exc.status == 401 and "MULTI_AGENT_API_TOKEN" in str(exc)


def test_contract_and_auth_errors_are_explained():
    with _env(MULTI_AGENT_ENABLED="true"):
        with _stub(lambda m, p, b=None: (200, {"workflow_id": WID})):
            exc = _raises(lambda: ma.workflow_status(WID), ma.MultiAgentError)
            assert exc.status == 502 and "missing required fields" in str(exc)
        with _stub(lambda m, p, b=None: (200, [1, 2])):
            assert _raises(lambda: ma.workflow(WID), ma.MultiAgentError).status == 502
        with _stub(lambda m, p, b=None: (401, {"error": "missing or invalid bearer token"})):
            exc = _raises(lambda: ma.workflow(WID), ma.MultiAgentError)
            assert exc.status == 401 and "MULTI_AGENT_API_TOKEN" in str(exc)
        with _stub(lambda m, p, b=None: (404, {"error": "unknown workflow 'wf_0a1b2c3d'"})):
            exc = _raises(lambda: ma.workflow("wf_0a1b2c3d"), ma.MultiAgentError)
            assert exc.status == 404 and "unknown workflow" in str(exc)


def test_workflow_ids_are_checked_before_anything_reaches_the_server():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        for bad in ("wf_x?", "wf_x%3F", "../health", "wf_0A1B2C3D", "wf_0a1b2c3", "", "wf_0a1b2c3d/status"):
            exc = _raises(lambda: ma.workflow_status(bad), ma.MultiAgentError)
            assert exc.status == 400 and "wf_1a2b3c4d" in str(exc), bad
            assert _raises(lambda: ma.decide(bad, "accept"), ma.MultiAgentError).status == 400
            assert _raises(lambda: ma.workflow(bad), ma.MultiAgentError).status == 400
        assert fake.calls == []
        c = _client()
        for path in ("/api/multi-agent/workflows/wf_x%3F", "/ui/multi-agent/workflows/wf_x%3F"):
            r = c.get(path)
            assert r.status_code in (400, 200), path
            assert b"wf_1a2b3c4d" in r.data, path
        r = c.post("/api/multi-agent/workflows/wf_x%3F/decision", headers=HX, json={"decision": "accept"})
        assert r.status_code == 400 and b"wf_1a2b3c4d" in r.data
        assert fake.calls == []


def test_server_failures_become_502_without_the_servers_text():
    with _env(MULTI_AGENT_ENABLED="true"):
        with _stub(lambda m, p, b=None: (500, {"error": "Traceback (most recent call last): secret path"})):
            exc = _raises(lambda: ma.workflow_status(WID), ma.MultiAgentError)
            assert exc.status == 502 and "Traceback" not in str(exc) and "HTTP 500" in str(exc)
            assert exc.temporary is True                                                # the server may answer later
            r = _client().get(f"/api/multi-agent/workflows/{WID}")
            assert r.status_code == 502 and "Traceback" not in r.get_data(as_text=True)
        with _stub(lambda m, p, b=None: (200, {"workflow_id": WID})):
            assert _raises(lambda: ma.workflow_status(WID), ma.MultiAgentError).temporary is False   # a broken contract will not
        with _stub(lambda m, p, b=None: (404, {"error": "unknown workflow"})):
            assert _raises(lambda: ma.workflow_status(WID), ma.MultiAgentError).temporary is False


# ---------------------------------------------------------------- routes

def _client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def test_health_and_agents_status_carry_the_integration():
    with _env(MULTI_AGENT_ENABLED="false", MULTI_AGENT_SERVER_URL="http://host.docker.internal:8300"):
        c = _client()
        h = c.get("/api/health").get_json()
        assert h["multi_agent"] == {"enabled": False, "url": "http://host.docker.internal:8300"}
        s = c.get("/api/agents/status").get_json()
        assert s["multi_agent"]["enabled"] is False and "mcp" in s and "rag" in s


def test_routes_report_disabled_and_unreachable_as_503_with_the_start_command():
    with _env(MULTI_AGENT_ENABLED="false"):
        c = _client()
        r = c.post("/api/multi-agent/workflows", headers=HX, json={"request": "x"})
        assert r.status_code == 503 and r.get_json()["disabled"] is True
        r = c.get("/ui/multi-agent/status")
        assert r.status_code == 200 and b"Inactive" in r.data and b"MULTI_AGENT_ENABLED=false" in r.data
        r = c.post("/ui/multi-agent/workflows", headers=HX, data={"request": "x", "customer_id": "1", "month": "9", "year": "2026"})
        assert r.status_code == 200 and b"disabled" in r.data
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/api/multi-agent/workflows", headers=HX, json={"request": "x"})
        assert r.status_code == 503 and r.get_json()["unreachable"] is True
        assert "python -m multi_agent_server.server" in r.get_json()["error"]
        r = c.get("/ui/multi-agent/status")
        assert r.status_code == 200 and b"Unreachable" in r.data and b"python -m multi_agent_server.server" in r.data


def test_routes_validate_input_before_calling_out():
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        assert c.post("/api/multi-agent/workflows", headers=HX, json={"request": "x", "month": 9.7}).status_code == 400
        assert c.post("/api/multi-agent/workflows", headers=HX, json={}).status_code == 400
        assert c.post("/api/multi-agent/workflows", headers=HX, json={"request": "x" * 1001}).status_code == 400
        assert c.post("/api/multi-agent/workflows", headers=HX, json={"request": "x", "month": "nine"}).status_code == 400
        assert c.post("/api/multi-agent/workflows", headers=HX, data="[1]", content_type="application/json").status_code == 400
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "maybe"})
        assert r.status_code == 400 and r.get_json()["options"] == list(ma.DECISIONS)
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "partially_accept"})
        assert r.status_code == 400 and "note" in r.get_json()["error"]
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "accept", "reviewer": "x" * 61})
        assert r.status_code == 400 and "reviewer" in r.get_json()["error"]


def test_routes_relay_the_workflow_lifecycle():
    from routes.agents import WORKFLOW_KEYS
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post("/api/multi-agent/workflows", headers=HX, json={"request": "Which categories went over?", "customer_id": 1, "month": 9, "year": 2026})
        assert r.status_code == 202 and r.get_json()["workflow_id"] == WID
        full = c.get(f"/api/multi-agent/workflows/{WID}").get_json()
        assert set(full) == set(WORKFLOW_KEYS)
        assert full["state"] == "awaiting_human_review" and full["final_response"] is None and full["request"] == REQUEST
        assert full["plan"]["objective"].startswith("Find") and full["review"]["verdict"] == "accept"
        assert full["result"]["answer"].startswith("Two categories")                    # the panel shows the whole workflow
        history = c.get("/api/multi-agent/workflows").get_json()
        assert history["count"] == 2 and [w["workflow_id"] for w in history["workflows"]] == [WID, OLDER_WID]   # budgeting only, newest first
        history = c.get("/api/multi-agent/workflows?customer_id=2").get_json()
        assert history == {"count": 0, "customer_id": 2, "workflows": []}
        assert c.get("/api/multi-agent/workflows?customer_id=two").status_code == 400
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "accept"})
        assert r.status_code == 200 and r.get_json()["state"] == "accepted" and r.get_json()["final_response"]["released"] is True
        assert fake.calls[-1][2]["by"] == "budgeting-ui"
        full = c.get(f"/api/multi-agent/workflows/{WID}").get_json()
        assert full["decision"]["decision"] == "accept" and full["final_response"]["released"] is True
        assert full["final_response"]["answer"].startswith("Two categories")
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "reject", "note": "x"})
        assert r.status_code == 409 and r.get_json()["state"] == "accepted"
        assert c.get("/api/multi-agent/workflows/wf_nope").status_code == 400          # not even a workflow id
        assert c.get("/api/multi-agent/workflows/wf_ffffffff").status_code == 404      # a well-formed id the server lacks


def test_other_features_workflows_do_not_exist_here():
    loans = FakeServer()

    def answer(method, path, body=None):
        status, payload = loans(method, path, body)
        if isinstance(payload, dict) and payload.get("feature") == "budgeting":
            payload = {**payload, "feature": "loans"}
        if path.startswith("/workflows"):
            payload = [{**w, "feature": "loans"} for w in payload]
        return status, payload

    with _env(MULTI_AGENT_ENABLED="true"), _stub(answer):
        c = _client()
        assert c.get(f"/api/multi-agent/workflows/{WID}").status_code == 404
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers=HX, json={"decision": "accept"})
        assert r.status_code == 404 and loans.decision is None                # never decided
        assert c.get("/api/multi-agent/workflows").get_json() == {"count": 0, "customer_id": None, "workflows": []}
        page = c.get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert "Unknown budgeting workflow" in page and "Dining Out" not in page
        page = c.get("/ui/multi-agent/history").get_data(as_text=True)
        assert "No workflows for customer 1 yet" in page and WID not in page
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "accept"})
        assert "Unknown budgeting workflow" in r.get_data(as_text=True) and loans.decision is None


def test_posts_need_the_same_origin_marker():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post("/api/multi-agent/workflows", json={"request": "x"})
        assert r.status_code == 403 and "HX-Request" in r.get_json()["error"]
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", json={"decision": "accept"})
        assert r.status_code == 403 and "HX-Request" in r.get_json()["error"]
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", data={"decision": "accept"})
        assert r.status_code == 200 and b"HX-Request" in r.data
        r = c.post("/ui/multi-agent/workflows", data={"request": "x", "customer_id": "1"})
        assert r.status_code == 200 and b"budgeting panel" in r.data
        assert fake.decision is None and all(m == "GET" or p != f"/workflow/{WID}/decision" for m, p, _b in fake.calls)
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers={"X-Requested-With": "XMLHttpRequest"},
                   json={"decision": "accept", "reviewer": "Bao"})
        assert r.status_code == 200 and fake.decision["by"] == "budgeting-ui:Bao"


def test_browsers_are_answered_only_from_the_tabs_on_the_apis_own_host():
    with _env(MULTI_AGENT_ENABLED="false"), _stub(FakeServer()) as fake:
        c = _client()                                                               # the test client's host is localhost
        for origin in ("http://localhost:3004", "http://localhost:3000"):
            r = c.get("/api/health", headers={"Origin": origin})
            assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == origin, origin
        exposed = r.headers.get("Access-Control-Expose-Headers", "")
        assert all(h in exposed for h in ("HX-Trigger", "HX-Retarget", "HX-Reswap"))   # the panel reads these cross-origin
        for origin in ("http://127.0.0.1:3004", "http://20.1.2.3:3004", "http://attacker.example:3000",
                       "http://evil.example", "http://localhost:5004", "http://localhost:30040", "not a url"):
            r = c.get("/api/health", headers={"Origin": origin})
            assert r.status_code == 403 and "own tab" in r.get_json()["error"], origin
            r = c.post(f"/api/multi-agent/workflows/{WID}/decision", headers={"Origin": origin, **HX}, json={"decision": "accept"})
            assert r.status_code == 403, origin                                     # refused before the route runs
        assert fake.decision is None and fake.calls == []
        assert c.get("/api/health").status_code == 200                              # server-side callers send no Origin
    with _env(MULTI_AGENT_ENABLED="false", BUDGET_FRONTEND_ORIGINS="https://demo.example.edu"):
        from app import create_app
        r = create_app().test_client().get("/api/health", headers={"Origin": "https://demo.example.edu"})
        assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "https://demo.example.edu"


# ---------------------------------------------------------------- fragments

def test_status_fragment_shows_pipeline_and_pending_when_reachable():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()):
        r = _client().get("/ui/multi-agent/status")
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and "Reachable" in page
        assert "planner" in page and "human" in page and "1 pending" in page


def test_start_fragment_returns_the_card_which_polls_itself_until_the_gate():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer(state="working")) as fake:
        c = _client()
        r = c.post("/ui/multi-agent/workflows", headers=HX, data={"request": "Which categories went over?", "customer_id": "1", "month": "9", "year": "2026"})
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and r.headers.get("HX-Trigger") == "ma-started"        # the history list refreshes
        assert f'id="ma-{WID}"' in page and f'hx-get="/ui/multi-agent/workflows/{WID}"' in page and 'hx-trigger="every 2s"' in page
        assert "htmx-indicator" in page and "working" in page and "ma-decision" not in page    # no decision before the gate
        assert c.get(f"/ui/multi-agent/workflows/{WID}").headers.get("HX-Trigger") is None   # still running: history unchanged
        fake.state = "awaiting_human_review"
        r = c.get(f"/ui/multi-agent/workflows/{WID}")
        page = r.get_data(as_text=True)
        assert 'hx-trigger="every 2s"' not in page                                   # polling stops at the gate
        assert r.headers.get("HX-Trigger") == "ma-updated"                           # and the history list refreshes
        for needle in ("Plan", "/api/budgets/summary", "Evidence", "Findings", "Dining Out is over by 25.2", "Answer",
                       "Review", "both named", "Decision", 'name="reviewer"', 'name="note"', "Partially accept (correct)",
                       f'hx-post="/ui/multi-agent/workflows/{WID}/decision"'):
            assert needle in page, needle
        assert "&lt;mock&gt;" in page and "<mock>" not in page                       # server text is escaped


def test_decision_block_posts_without_a_form_and_refreshes_history():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        card = c.get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        block = card.split('class="ma-section ma-decision"')[1]
        assert "<form" not in block                                                    # Enter in the name box submits nothing
        assert block.count(f'hx-post="/ui/multi-agent/workflows/{WID}/decision"') == 3 and 'type="button"' in block
        for value in ma.DECISIONS:
            assert f'hx-vals=\'{{"decision": "{value}"}}\'' in block, value
        for needle in ('hx-include="closest .ma-decision"', 'hx-sync="closest .ma-decision:drop"', f'hx-target="#ma-msg-{WID}"',
                       'hx-swap="innerHTML"', 'hx-disabled-elt="this"', 'name="reviewer"', 'name="note"', 'maxlength="60"',
                       f'id="ma-msg-{WID}"'):
            assert needle in block, needle
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "accept", "reviewer": "Bao"})
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and r.headers.get("HX-Trigger") == "ma-decided"
        assert r.headers.get("HX-Retarget") == f"#ma-{WID}" and r.headers.get("HX-Reswap") == "outerHTML"   # the whole card replaces the article
        assert f'id="ma-{WID}"' in page and "accepted" in page and "budgeting-ui:Bao" in page and "ma-decision" not in page
        assert fake.decision["by"] == "budgeting-ui:Bao"
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "reject"})
        assert r.headers.get("HX-Trigger") == "ma-updated" and r.headers.get("HX-Retarget") == f"#ma-{WID}"
        assert b"not awaiting_human_review" in r.data and f'id="ma-{WID}"'.encode() in r.data   # decided already: the card as it is now
        assert fake.decision["decision"] == "accept"


def test_refused_or_failed_decisions_keep_the_block_and_its_note():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "partially_accept", "note": ""})
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and "needs a note" in page and "HX-Retarget" not in r.headers and "HX-Trigger" not in r.headers
        assert "<article" not in page and 'id="ma-' not in page                       # only the reason, into the slot
        assert fake.decision is None

    def down(method, path, body=None):
        if method == "POST":
            raise ma.MultiAgentUnreachable("Multi-Agent Server at http://localhost:8300/x refused the connection - start it")
        return FakeServer()(method, path, body)
    with _env(MULTI_AGENT_ENABLED="true"), _stub(down):
        r = _client().post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "accept"})
        page = r.get_data(as_text=True)
        assert "Try again" in page and "<article" not in page and "HX-Retarget" not in r.headers   # the typed note stays on the page

    def failing(method, path, body=None):
        if method == "POST":
            return 503, {"error": "model unavailable"}
        return FakeServer()(method, path, body)
    with _env(MULTI_AGENT_ENABLED="true"), _stub(failing):
        page = _client().post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "accept"}).get_data(as_text=True)
        assert "Try again" in page and "HTTP 503" in page and "<article" not in page


def test_history_fragment_lists_the_selected_customers_workflows_newest_first():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        page = _client().get("/ui/multi-agent/history?customer_id=1&month=9&year=2026").get_data(as_text=True)
        assert fake.calls[-1][1] == f"/workflows?feature=budgeting&limit={ma.HISTORY_LIMIT}&customer_id=1"
        assert WID in page and OLDER_WID in page and page.index(WID) < page.index(OLDER_WID)
        assert LOANS_WID not in page and "List my loans" not in page
        assert f'hx-get="/ui/multi-agent/workflows/{WID}"' in page and 'hx-target="#ma-panel"' in page
        assert "awaiting_human_review" in page and REQUEST in page and "Customer 1, 9/2026" in page
        page = _client().get("/ui/multi-agent/history?customer_id=2").get_data(as_text=True)
        assert "No workflows for customer 2 yet" in page and WID not in page            # another customer's questions stay out
    with _env(MULTI_AGENT_ENABLED="false"):
        r = _client().get("/ui/multi-agent/history")
        assert r.status_code == 200 and b"MULTI_AGENT_ENABLED=false" in r.data and b"<ul" not in r.data
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        r = _client().get("/ui/multi-agent/history")
        assert r.status_code == 200 and b"python -m multi_agent_server.server" in r.data


def test_temporary_failures_keep_the_card_polling():
    def down(method, path, body=None):
        raise ma.MultiAgentUnreachable("Multi-Agent Server at http://localhost:8300/x refused the connection - start it")
    with _env(MULTI_AGENT_ENABLED="true"), _stub(down):
        page = _client().get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert f'id="ma-{WID}"' in page and "retrying" in page and 'hx-trigger="every 5s"' in page
        assert f'hx-get="/ui/multi-agent/workflows/{WID}"' in page and "Checking again" in page
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (500, {"error": "boom"})):
        page = _client().get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert "retrying" in page and "boom" not in page
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (404, {"error": f"unknown workflow '{WID}'"})):
        page = _client().get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert "retrying" not in page and "unknown workflow" in page              # gone for good: no point polling
    with _env(MULTI_AGENT_ENABLED="true"), _stub(lambda m, p, b=None: (200, {"workflow_id": WID, "feature": "budgeting"})):
        r = _client().get(f"/ui/multi-agent/workflows/{WID}")
        page = r.get_data(as_text=True)
        assert "retrying" not in page and "missing required fields" in page and r.headers.get("HX-Trigger") is None   # a broken record will not fix itself


def test_frontend_tabs_wire_the_panel_and_carry_no_inner_header():
    tabs = BASE_DIR.parent / "frontend" / "tabs"
    html = (tabs / "ai-mode.html").read_text(encoding="utf-8")
    normal = (tabs / "budgets.html").read_text(encoding="utf-8")
    # the Normal tab keeps the budget sections and links to the AI Mode tab; every AI panel lives on the AI Mode tab
    assert 'href="/tabs/ai-mode.html"' in normal and 'id="create-form"' in normal and 'hx-get="/ui/budgets"' in normal
    for ai_only in ('hx-post="/ui/insight"', 'hx-post="/ui/mcp/tool"', 'hx-post="/ui/rag/query"',
                    'hx-post="/ui/multi-agent/workflows"', 'id="ma-history"'):
        assert ai_only not in normal and ai_only in html, ai_only
    assert 'href="/tabs/budgets.html"' in html and 'id="period-form"' in html
    for page in (html, normal):
        assert "app-header" not in page and "brand-mark" not in page           # the shell on port 3000 carries the SmartBank header
        assert 'class="feature-nav tab-strip"' in page
    for needle in (
        'hx-get="/ui/multi-agent/status"', 'hx-post="/ui/multi-agent/workflows"', 'hx-get="/ui/multi-agent/history"',
        'id="ma-panel"', 'id="ma-history"', 'name="request"', 'maxlength="1000"', 'hx-include="#period-form"', "ma-chip",
        'hx-disabled-elt="find button[type=submit]"',
        'hx-trigger="load, change from:#period-form, ma-started from:body, ma-updated from:body, ma-decided from:body"',
    ):
        assert needle in html, needle
    assert 'hx-include="#period-form"' in html.split('id="ma-history"')[1].split(">")[0]   # the history follows the selected customer
    for gone in ("ma-desk", "ma-token", "X-Reviewer-Token", "ma-pending", "sessionStorage", "/response",
                 "create-form", ".inline-edit", "td.actions", ".tab-strip {"):
        assert gone not in html, gone
    shared_css = (BASE_DIR.parents[2] / "shared" / "frontend" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".tab-strip {" in shared_css and ".tab-strip {" not in normal                  # the strip rules live once, in the shared stylesheet
    assert ".summary-strip" in html and ".stat " in html                                 # the MCP summary still needs these here
    from app import app
    ui_rules = {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/ui/multi-agent")}
    assert ui_rules == {"/ui/multi-agent/status", "/ui/multi-agent/workflows", "/ui/multi-agent/workflows/<workflow_id>",
                        "/ui/multi-agent/workflows/<workflow_id>/decision", "/ui/multi-agent/history"}
    api_rules = {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api/multi-agent")}
    assert api_rules == {"/api/multi-agent/workflows", "/api/multi-agent/workflows/<workflow_id>",
                         "/api/multi-agent/workflows/<workflow_id>/decision"}


def test_decision_fragment_renders_the_released_or_withheld_response():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "partially_accept", "note": ""})
        assert r.status_code == 200 and b"needs a note" in r.data and b"<article" not in r.data    # the reason, into the slot
        assert fake.decision is None
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX, data={"decision": "partially_accept", "note": "Say the period"})
        page = r.get_data(as_text=True)
        assert r.headers.get("HX-Retarget") == f"#ma-{WID}"
        assert "partially_accepted" in page and "Final response" in page and "Two categories" in page and "Say the period" in page
        assert "ma-decision" not in page                                                           # no second decision offered
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()):
        page = _client().post(f"/ui/multi-agent/workflows/{WID}/decision", headers=HX,
                              data={"decision": "reject", "note": "wrong month"}).get_data(as_text=True)
        assert "rejected" in page and "withheld" in page and "wrong month" in page
        assert "Two categories" not in page.split("Final response")[-1]


def test_failed_workflow_card_shows_the_structured_error():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer(state="failed")):
        page = _client().get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert "failed" in page and "budgeting service unavailable" in page and 'hx-trigger="every 2s"' not in page


def test_fragment_validates_the_form_before_calling_out():
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/ui/multi-agent/workflows", headers=HX, data={"request": "", "customer_id": "1"})
        assert r.status_code == 200 and b"request" in r.data.lower()
        r = c.post("/ui/multi-agent/workflows", headers=HX, data={"request": "x" * 1001, "customer_id": "1"})
        assert r.status_code == 200 and b"1000" in r.data


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
