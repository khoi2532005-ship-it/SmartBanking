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
STAGES_DONE = [
    {"role": "planner", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 2.1, "fallback": False},
    {"role": "worker", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 1.5, "fallback": False},
    {"role": "reviewer", "attempt": 1, "status": "completed", "model": "gemini / g", "duration_seconds": 1.8, "fallback": False},
    {"role": "human", "attempt": 1, "status": "running", "model": "human", "duration_seconds": None, "fallback": False},
]
SUMMARY_AWAITING = {"workflow_id": WID, "feature": "budgeting", "state": "awaiting_human_review", "stages": STAGES_DONE,
                    "revisions": 0, "has_plan": True, "has_result": True, "has_review": True, "decision": None,
                    "released": False, "error": "", "created_at": "2026-10-18T01:00:00+00:00", "updated_at": "2026-10-18T01:00:07+00:00"}
FULL_AWAITING = {
    **SUMMARY_AWAITING,
    "request": "Which categories went over budget in September 2026?",
    "context": {"customer_id": 1, "month": 9, "year": 2026},
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
            return 200, {**SUMMARY_AWAITING, "state": self.state}
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
        if path == f"/workflow/{WID}/response":
            if self.decision is None:
                return 409, {"error": "no response yet: the workflow has not been decided by a human", "state": self.state,
                             "awaiting_decision": self.state == "awaiting_human_review"}
            return 200, self._final()
        if path == "/workflows/pending":
            return 200, {"count": 1, "options": list(ma.DECISIONS), "workflows": [SUMMARY_AWAITING]}
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
        with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL="http://host.docker.internal:8300/", MULTI_AGENT_API_TOKEN="s3cret"):
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


def test_response_is_409_until_decided_then_the_contract():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        exc = _raises(lambda: ma.response(WID), ma.MultiAgentError)
        assert exc.status == 409 and exc.payload["awaiting_decision"] is True
        ma.decide(WID, "accept")
        final = ma.response(WID)
        assert final["released"] is True and final["answer"].startswith("Two categories")
        fake.calls.clear()


def test_contract_and_auth_errors_are_explained():
    with _env(MULTI_AGENT_ENABLED="true"):
        with _stub(lambda m, p, b=None: (200, {"workflow_id": WID})):
            exc = _raises(lambda: ma.workflow_status(WID), ma.MultiAgentError)
            assert exc.status == 502 and "missing required fields" in str(exc)
        with _stub(lambda m, p, b=None: (200, [1, 2])):
            assert _raises(lambda: ma.pending(), ma.MultiAgentError).status == 502
        with _stub(lambda m, p, b=None: (401, {"error": "missing or invalid bearer token"})):
            exc = _raises(lambda: ma.pending(), ma.MultiAgentError)
            assert exc.status == 401 and "MULTI_AGENT_API_TOKEN" in str(exc)
        with _stub(lambda m, p, b=None: (404, {"error": "unknown workflow 'wf_x'"})):
            exc = _raises(lambda: ma.workflow("wf_x"), ma.MultiAgentError)
            assert exc.status == 404 and "unknown workflow" in str(exc)


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
        r = c.post("/api/multi-agent/workflows", json={"request": "x"})
        assert r.status_code == 503 and r.get_json()["disabled"] is True
        r = c.get("/ui/multi-agent/status")
        assert r.status_code == 200 and b"Inactive" in r.data and b"MULTI_AGENT_ENABLED=false" in r.data
        r = c.post("/ui/multi-agent/workflows", data={"request": "x", "customer_id": "1", "month": "9", "year": "2026"})
        assert r.status_code == 200 and b"disabled" in r.data
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/api/multi-agent/workflows", json={"request": "x"})
        assert r.status_code == 503 and r.get_json()["unreachable"] is True
        assert "python -m multi_agent_server.server" in r.get_json()["error"]
        r = c.get("/ui/multi-agent/status")
        assert r.status_code == 200 and b"Unreachable" in r.data and b"python -m multi_agent_server.server" in r.data


def test_routes_validate_input_before_calling_out():
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        assert c.post("/api/multi-agent/workflows", json={}).status_code == 400
        assert c.post("/api/multi-agent/workflows", json={"request": "x" * 1001}).status_code == 400
        assert c.post("/api/multi-agent/workflows", json={"request": "x", "month": "nine"}).status_code == 400
        assert c.post("/api/multi-agent/workflows", data="[1]", content_type="application/json").status_code == 400
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", json={"decision": "maybe"})
        assert r.status_code == 400 and r.get_json()["options"] == list(ma.DECISIONS)
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", json={"decision": "partially_accept"})
        assert r.status_code == 400 and "note" in r.get_json()["error"]


def test_routes_relay_the_workflow_lifecycle():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post("/api/multi-agent/workflows", json={"request": "Which categories went over?", "customer_id": 1, "month": 9, "year": 2026})
        assert r.status_code == 202 and r.get_json()["workflow_id"] == WID
        assert c.get(f"/api/multi-agent/workflows/{WID}").get_json()["state"] == "awaiting_human_review"
        panel = c.get(f"/api/multi-agent/workflows/{WID}/review-panel").get_json()
        assert panel["plan"]["objective"].startswith("Find") and panel["review"]["verdict"] == "accept"
        assert panel["result"]["answer"].startswith("Two categories")
        r = c.get(f"/api/multi-agent/workflows/{WID}/response")
        assert r.status_code == 409 and r.get_json()["awaiting_decision"] is True
        assert c.get("/api/multi-agent/pending").get_json()["count"] == 1
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", json={"decision": "accept"})
        assert r.status_code == 200 and r.get_json()["state"] == "accepted" and r.get_json()["final_response"]["released"] is True
        assert fake.calls[-1][2]["by"] == "budgeting-ui"
        r = c.get(f"/api/multi-agent/workflows/{WID}/response")
        assert r.status_code == 200 and r.get_json()["released"] is True
        r = c.post(f"/api/multi-agent/workflows/{WID}/decision", json={"decision": "reject", "note": "x"})
        assert r.status_code == 409 and r.get_json()["state"] == "accepted"
        assert c.get("/api/multi-agent/workflows/wf_nope").status_code == 404


# ---------------------------------------------------------------- fragments

def test_status_fragment_shows_pipeline_and_pending_when_reachable():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()):
        r = _client().get("/ui/multi-agent/status")
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and "Reachable" in page
        assert "planner" in page and "human" in page and "1 pending" in page


def test_workflow_card_polls_while_running_and_stops_at_the_gate():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer(state="working")) as fake:
        c = _client()
        r = c.post("/ui/multi-agent/workflows", data={"request": "Which categories went over?", "customer_id": "1", "month": "9", "year": "2026"})
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and f'id="ma-{WID}"' in page
        assert f'hx-get="/ui/multi-agent/workflows/{WID}"' in page and 'hx-trigger="every 2s"' in page
        assert "htmx-indicator" in page and "working" in page
        fake.state = "awaiting_human_review"
        page = c.get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert 'hx-trigger="every 2s"' not in page                       # polling stops
        for needle in ("Plan", "/api/budgets/summary", "Evidence", "Findings", "Dining Out is over by 25.2",
                       "Answer", "Review", "accept", "both named", 'name="decision"', 'value="partially_accept"',
                       'name="note"', f'hx-post="/ui/multi-agent/workflows/{WID}/decision"'):
            assert needle in page, needle
        assert "&lt;mock&gt;" in page and "<mock>" not in page             # server text is escaped


def test_decision_fragment_renders_the_released_or_withheld_response():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        c = _client()
        r = c.post(f"/ui/multi-agent/workflows/{WID}/decision", data={"decision": "partially_accept", "note": ""})
        assert r.status_code == 200 and b"needs a note" in r.data            # the card comes back with the reason
        assert fake.decision is None
        page = c.post(f"/ui/multi-agent/workflows/{WID}/decision", data={"decision": "partially_accept", "note": "Say the period"}).get_data(as_text=True)
        assert "partially_accepted" in page and "Final response" in page and "Two categories" in page and "Say the period" in page
        assert 'name="decision"' not in page                                 # no second decision offered
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer()) as fake:
        page = _client().post(f"/ui/multi-agent/workflows/{WID}/decision", data={"decision": "reject", "note": "wrong month"}).get_data(as_text=True)
        assert "rejected" in page and "withheld" in page and "wrong month" in page and "Two categories" not in page.split("Final response")[-1]


def test_failed_workflow_card_shows_the_structured_error():
    with _env(MULTI_AGENT_ENABLED="true"), _stub(FakeServer(state="failed")):
        page = _client().get(f"/ui/multi-agent/workflows/{WID}").get_data(as_text=True)
        assert "failed" in page and "budgeting service unavailable" in page and 'hx-trigger="every 2s"' not in page


def test_fragment_validates_the_form_before_calling_out():
    with _env(MULTI_AGENT_ENABLED="true", MULTI_AGENT_SERVER_URL=DEAD_PORT_URL):
        c = _client()
        r = c.post("/ui/multi-agent/workflows", data={"request": "", "customer_id": "1"})
        assert r.status_code == 200 and b"request" in r.data.lower()
        r = c.post("/ui/multi-agent/workflows", data={"request": "x" * 1001, "customer_id": "1"})
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
