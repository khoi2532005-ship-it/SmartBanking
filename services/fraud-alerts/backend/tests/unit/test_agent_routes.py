"""fraud-service's /api/agents routes against the real Multi-Agent Server app.

The server's Flask app runs in this process (inline executor, scripted model,
fake feature API) and the fraud client's requests.request is pointed at its
test client, so the client, the routes and the server's contract are tested
together: no network, no API key, no fake server.
"""

import json

import pytest
import requests

from multi_agent_server import evidence
from multi_agent_server.http import FetchResult
from multi_agent_server.orchestrator import InlineExecutor
from multi_agent_server.server import create_app as create_server
from services import multi_agent_client
from tests.unit.helpers import FakeResponse

ALERTS = [{"alert_id": 1, "severity": "high", "status": "new"}, {"alert_id": 11, "severity": "high", "status": "reviewed"}]
PLAN = {"objective": "Count this customer's alerts", "success_criteria": ["Every alert status is counted"], "limitations": [],
        "tasks": [{"id": "t1", "kind": "api", "title": "Alerts", "endpoint": "/api/alerts", "params": {"customer_id": 1}, "evidence": "counts"},
                  {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "summarise", "evidence": "x"}]}
RESULT = {"findings": [{"task_id": "t2", "statement": "Customer 1 has 2 alerts, both high severity: 1 new and 1 reviewed.",
                        "evidence": ["t1"]}],
          "answer": "2 high-severity alerts: 1 new and 1 reviewed. Review the new one first.", "gaps": []}
REVIEW = {"verdict": "accept", "summary": "Counts match the evidence.", "criteria": [{"index": 1, "met": True, "note": "counted"}],
          "defects": [], "risks": ["Counts only: amounts were not checked"], "revision_notes": []}


def scripted_ask(system_prompt, user_prompt, **kwargs):
    if "PLANNER" in system_prompt:
        return json.dumps(PLAN)
    return json.dumps(RESULT if "WORKER" in system_prompt else REVIEW)


def fake_fetch(base_url, path, params=None):
    payload = ALERTS if path == "/api/alerts" else []
    return FetchResult(url=f"{base_url}{path}", status_code=200, payload=payload, duration_seconds=0.01)


class Harness:
    """The real server behind the fraud client, plus the fraud app itself."""

    def __init__(self, app, server):
        self.app = app
        self.server = server.test_client()
        self.calls = []
        self._audit = server.extensions["multi_agent"]["audit"]

    def transport(self, method, url, **kwargs):
        path = url.removeprefix(multi_agent_client.server_url())
        self.calls.append((method, path))
        reply = self.server.open(path, method=method, json=kwargs.get("json"), headers=kwargs.get("headers") or {})
        return FakeResponse(reply.status_code, reply.get_json())

    def coordination(self):
        return self._audit.read_coordination()


@pytest.fixture
def h(tmp_path, monkeypatch, client):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
    monkeypatch.delenv("MULTI_AGENT_API_TOKEN", raising=False)
    monkeypatch.setattr(evidence, "fetch", fake_fetch)
    server = create_server(data_dir=tmp_path / "data", audit_dir=tmp_path / "audit",
                           executor=InlineExecutor(), ask=scripted_ask, api_token="")
    harness = Harness(client, server)
    monkeypatch.setattr(multi_agent_client.requests, "request", harness.transport)
    return harness


def start(h, task="Summarise this customer's fraud alerts by severity and status.", customer_id=1):
    r = h.app.post("/api/agents/workflow", json={"task": task, "customer_id": customer_id})
    assert r.status_code == 202, r.get_json()
    return r.get_json()["workflow_id"]


def test_workflow_runs_to_human_review(h):
    w = h.app.get(f"/api/agents/workflow/{start(h)}").get_json()
    assert (w["feature"], w["state"], w["context"]) == ("fraud", "awaiting_human_review", {"customer_id": 1})
    assert w["plan"]["tasks"][0]["endpoint"] == "/api/alerts"
    assert (w["result"]["answer"], w["review"]["verdict"], w["final_response"]) == (RESULT["answer"], "accept", None)


@pytest.mark.parametrize("decision, note, state, released", [
    ("accept", "", "accepted", True),
    ("partially_accept", "Name the new alert", "partially_accepted", True),
    ("reject", "Counts look stale", "rejected", False),
])
def test_review_finalises_and_is_audited(h, decision, note, state, released):
    wid = start(h)
    r = h.app.post(f"/api/agents/workflow/{wid}/review", json={"decision": decision, "note": note, "reviewer": "Khoi"})
    assert r.status_code == 200, r.get_json()
    w = h.app.get(f"/api/agents/workflow/{wid}").get_json()
    assert w["state"] == state and w["final_response"]["released"] is released
    assert [c["detail"]["by"] for c in h.coordination() if c["decision"] == "human_decision"] == ["fraud-ui:Khoi"]


def test_second_decision_is_409_and_changes_nothing(h):
    wid = start(h)
    assert h.app.post(f"/api/agents/workflow/{wid}/review", json={"decision": "accept", "reviewer": "Khoi"}).status_code == 200
    r = h.app.post(f"/api/agents/workflow/{wid}/review", json={"decision": "reject", "note": "late", "reviewer": "Khoi"})
    assert r.status_code == 409 and r.get_json()["state"] == "accepted"
    assert h.app.get(f"/api/agents/workflow/{wid}").get_json()["state"] == "accepted"


@pytest.mark.parametrize("body, message", [
    ({"decision": "partially_accept", "note": "   ", "reviewer": "Khoi"}, "partially_accept needs a note saying what to correct"),
    ({"decision": "partially_accept", "note": "x" * 1001, "reviewer": "Khoi"}, "note must be 1000 characters or fewer"),
    ({"decision": "approve", "reviewer": "Khoi"}, "decision must be one of accept, partially_accept, reject"),
    ({"decision": "accept", "reviewer": "r" * 61}, "reviewer must be 60 characters or fewer"),
    ({"decision": "accept"}, "reviewer is required: enter your name, it is recorded in the audit"),
    ({"decision": "accept", "reviewer": "   "}, "reviewer is required: enter your name, it is recorded in the audit"),
])
def test_bad_review_is_400_before_reaching_the_server(h, body, message):
    wid = start(h)
    before = len(h.calls)
    r = h.app.post(f"/api/agents/workflow/{wid}/review", json=body)
    assert (r.status_code, r.get_json()["error"]) == (400, message) and len(h.calls) == before


def test_text_plain_posts_are_refused(h):  # a cross-site form can send text/plain with no CORS preflight
    wid = start(h)
    before = len(h.calls)
    r = h.app.post(f"/api/agents/workflow/{wid}/review", data='{"decision": "accept"}', content_type="text/plain")
    assert r.status_code == 400 and len(h.calls) == before


@pytest.mark.parametrize("body, message", [
    ({"customer_id": 1}, "task is required"),
    ({"task": "   ", "customer_id": 1}, "task is required"),
    ({"task": "x" * 1001, "customer_id": 1}, "task must be 1000 characters or fewer"),
    ({"task": "Summarise"}, "customer_id must be a positive integer"),
    ({"task": "Summarise", "customer_id": "0"}, "customer_id must be a positive integer"),
])
def test_bad_start_is_400_before_reaching_the_server(h, body, message):
    r = h.app.post("/api/agents/workflow", json=body)
    assert (r.status_code, r.get_json()["error"]) == (400, message) and h.calls == []


def test_other_features_workflows_are_invisible_here(h):
    other = h.server.post("/workflow", json={"feature": "loans", "request": "List my loans",
                                             "context": {"customer_id": 1}}).get_json()["workflow_id"]
    state = h.server.get(f"/workflow/{other}/status").get_json()["state"]
    assert h.app.get(f"/api/agents/workflow/{other}").status_code == 404
    assert h.app.post(f"/api/agents/workflow/{other}/review", json={"decision": "accept", "reviewer": "Khoi"}).status_code == 404
    assert h.server.get(f"/workflow/{other}/status").get_json()["state"] == state
    mine = start(h)
    history = h.app.get("/api/agents/workflows").get_json()
    assert history["count"] == 1 and [w["workflow_id"] for w in history["workflows"]] == [mine]


@pytest.mark.parametrize("wid", ["wf_x%3F", "WF_1A2B3C4D", "wf_1a2b3c4d5", "wf_1a2b3c4d%0A"])
def test_malformed_ids_never_reach_the_server(h, wid):
    assert h.app.get(f"/api/agents/workflow/{wid}").status_code == 400
    assert h.app.post(f"/api/agents/workflow/{wid}/review", json={"decision": "accept"}).status_code == 400
    assert h.calls == []


def test_disabled_server_is_503_disabled(client, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    r = client.post("/api/agents/workflow", json={"task": "Summarise", "customer_id": 1})
    assert r.status_code == 503 and r.get_json()["disabled"] is True


def test_unreachable_server_is_503_with_the_start_command(client, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("Connection refused")

    monkeypatch.setattr(multi_agent_client.requests, "request", refuse)
    body = client.get("/api/agents/workflows").get_json()
    assert body["unreachable"] is True and "python -m multi_agent_server.server" in body["error"]
