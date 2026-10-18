"""The Multi-Agent client: flag, transport failures, fraud-only scope, decisions."""

import types

import pytest
import requests

from services import multi_agent_client as ma
from services.local_servers import BadServerResponse, ServerDisabled, ServerUnavailable
from tests.unit.helpers import FakeResponse

URL = "http://ma.test:8300"
SUMMARY = {"workflow_id": "wf_0a1b2c3d", "feature": "fraud", "state": "planning", "stages": []}


@pytest.fixture
def server(monkeypatch):
    """Stands in for requests.request: returns (or raises) replies[(method, path)] and records every call."""
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_SERVER_URL", URL + "/")
    monkeypatch.delenv("MULTI_AGENT_API_TOKEN", raising=False)
    fake = types.SimpleNamespace(calls=[], replies={})

    def request(method, url, **kwargs):
        fake.calls.append((method, url.removeprefix(URL), kwargs))
        reply = fake.replies[(method, url.removeprefix(URL))]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(ma.requests, "request", request)
    return fake


def test_disabled_raises_before_any_call(server, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    with pytest.raises(ServerDisabled, match="MULTI_AGENT_ENABLED=false"):
        ma.history()
    assert server.calls == []


def test_start_posts_one_fraud_workflow_for_one_customer(server, monkeypatch):
    server.replies[("POST", "/workflow")] = FakeResponse(202, SUMMARY)
    assert ma.start("Summarise alerts", 3) == SUMMARY
    method, path, kwargs = server.calls[0]
    assert (method, path, kwargs["timeout"]) == ("POST", "/workflow", (2, 10))
    assert kwargs["json"] == {"feature": "fraud", "request": "Summarise alerts", "context": {"customer_id": 3}}
    assert "Authorization" not in kwargs["headers"]
    monkeypatch.setenv("MULTI_AGENT_API_TOKEN", "test-token")
    ma.start("Summarise alerts", 3)
    assert server.calls[1][2]["headers"]["Authorization"] == "Bearer test-token"


@pytest.mark.parametrize("reply, error, text", [
    (requests.ConnectionError("Connection refused"), ServerUnavailable,
     "is not reachable. Start it on the host with: python -m multi_agent_server.server"),
    (requests.ReadTimeout("read timed out"), ServerUnavailable, "did not answer in time"),
    (FakeResponse(401, {"error": "missing or invalid bearer token"}), ServerUnavailable, "MULTI_AGENT_API_TOKEN"),
    (FakeResponse(500, {"error": "KeyError: plan"}), BadServerResponse, "Multi-Agent Server failed (HTTP 500)"),
    (FakeResponse(200, "<html>not json</html>"), BadServerResponse, "answered HTTP 200 without JSON"),
])
def test_transport_failures_are_readable(server, reply, error, text):
    server.replies[("GET", "/workflows")] = reply
    with pytest.raises(error) as info:
        ma.history()
    assert text in str(info.value) and "KeyError" not in str(info.value)


@pytest.mark.parametrize("reply, message", [
    (FakeResponse(404, {"error": "unknown workflow 'wf_0a1b2c3d'"}), "unknown workflow 'wf_0a1b2c3d'"),
    (FakeResponse(200, {**SUMMARY, "feature": "loans"}), "unknown fraud workflow wf_0a1b2c3d"),
])
def test_unknown_and_other_feature_workflows_are_404(server, reply, message):
    server.replies[("GET", "/workflow/wf_0a1b2c3d")] = reply
    with pytest.raises(ma.WorkflowRefused) as info:
        ma.workflow("wf_0a1b2c3d")
    assert (info.value.status, str(info.value)) == (404, message)


@pytest.mark.parametrize("reviewer, by", [("Khoi", "fraud-ui:Khoi"), ("", "fraud-ui")])
def test_review_posts_the_decision_and_who_made_it(server, reviewer, by):
    server.replies[("GET", "/workflow/wf_0a1b2c3d/status")] = FakeResponse(200, {**SUMMARY, "state": "awaiting_human_review"})
    server.replies[("POST", "/workflow/wf_0a1b2c3d/decision")] = FakeResponse(200, {**SUMMARY, "state": "accepted"})
    assert ma.review("wf_0a1b2c3d", "accept", "", reviewer)["state"] == "accepted"
    assert server.calls[1][2]["json"] == {"decision": "accept", "note": "", "by": by}


def test_history_keeps_only_fraud_workflows(server):
    budgeting = {**SUMMARY, "workflow_id": "wf_99999999", "feature": "budgeting"}
    server.replies[("GET", "/workflows")] = FakeResponse(200, [SUMMARY, budgeting])
    assert [w["workflow_id"] for w in ma.history()] == ["wf_0a1b2c3d"]
    server.replies[("GET", "/workflows")] = FakeResponse(200, {"workflows": []})
    with pytest.raises(BadServerResponse):
        ma.history()


def test_health_reports_the_multi_agent_flag(client, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    monkeypatch.setenv("MULTI_AGENT_SERVER_URL", "http://host.docker.internal:8300")
    assert client.get("/api/health").get_json()["multi_agent"] == {"enabled": False, "url": "http://host.docker.internal:8300"}
