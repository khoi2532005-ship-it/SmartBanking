"""Tests for the shared Multi-Agent Server.

Everything runs against a Flask test client with temporary data and audit
directories, so no server, model or API key is needed. Commit 1 covers the
skeleton: request validation, the workflow store and the two audit files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("flask")

from multi_agent_server import config  # noqa: E402
from multi_agent_server.models import State  # noqa: E402
from multi_agent_server.server import create_app  # noqa: E402

VALID = {"feature": "budgeting", "request": "review this month's budget performance",
         "context": {"customer_id": 1, "month": 9, "year": 2026}}


@pytest.fixture
def app(tmp_path):
    application = create_app(data_dir=tmp_path / "data", audit_dir=tmp_path / "audit")
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------- health

def test_health_reports_roles_models_and_audit_paths(client, tmp_path):
    body = client.get("/health").get_json()
    assert body["service"] == "multi-agent-server" and body["status"] == "running"
    assert body["roles"] == ["planner", "worker", "reviewer"]
    assert set(body["models"]) == {"planner", "worker", "reviewer"}
    assert body["features"] == list(config.FEATURES)
    assert body["audit"]["workflow_history"].endswith("workflow_history.jsonl")
    assert body["audit"]["coordination_audit"].endswith("coordination_audit.jsonl")
    assert body["workflows"] == 0


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("body, word", [
    ("[1]", "JSON object"),
    ({}, "feature"),
    ({"feature": "payments", "request": "x"}, "feature"),
    ({"feature": "budgeting"}, "request is required"),
    ({"feature": "budgeting", "request": "x" * 1001}, "1000 characters"),
    ({"feature": "budgeting", "request": "x", "context": [1]}, "context must be"),
    ({"feature": "budgeting", "request": "x", "context": {"month": 13}}, "context.month"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": "abc"}}, "context.customer_id"),
])
def test_bad_requests_are_400_with_a_reason(client, body, word):
    if isinstance(body, str):
        response = client.post("/workflow", data=body, content_type="application/json")
    else:
        response = client.post("/workflow", json=body)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert word in response.get_json()["error"], response.get_json()


def test_unknown_feature_lists_the_allowed_ones(client):
    body = client.post("/workflow", json={"feature": "payments", "request": "x"}).get_json()
    assert body["allowed_features"] == list(config.FEATURES)


# ---------------------------------------------------------------- create + read

def test_create_workflow_records_state_and_both_audit_files(client, app, tmp_path):
    response = client.post("/workflow", json=VALID)
    assert response.status_code == 202
    body = response.get_json()
    workflow_id = body["workflow_id"]
    assert workflow_id.startswith("wf_") and len(workflow_id) == 11
    assert body["state"] == State.CREATED
    assert body["links"] == {"self": f"/workflow/{workflow_id}", "status": f"/workflow/{workflow_id}/status"}

    full = client.get(f"/workflow/{workflow_id}").get_json()
    assert full["feature"] == "budgeting" and full["request"] == VALID["request"]
    assert full["context"] == {"customer_id": 1, "month": 9, "year": 2026}
    assert full["stages"] == [] and full["plan"] is None and full["decision"] is None

    status = client.get(f"/workflow/{workflow_id}/status").get_json()
    assert status["state"] == State.CREATED and status["has_plan"] is False

    history = _lines(tmp_path / "audit" / "workflow_history.jsonl")
    coordination = _lines(tmp_path / "audit" / "coordination_audit.jsonl")
    assert [r["event"] for r in history] == ["workflow_created"]
    assert history[0]["workflow_id"] == workflow_id and history[0]["state"] == State.CREATED
    assert history[0]["detail"]["context"]["month"] == 9
    assert [r["decision"] for r in coordination] == ["request_accepted"]
    assert coordination[0]["detail"]["stages"] == ["planner", "worker", "reviewer", "human"]
    for record in history + coordination:
        assert record["ts"].endswith("+00:00")        # UTC, so logs from several machines line up

    assert client.get("/health").get_json()["workflows"] == 1


def test_unknown_workflow_is_a_json_404(client):
    response = client.get("/workflow/wf_deadbeef")
    assert response.status_code == 404 and "unknown workflow" in response.get_json()["error"]
    response = client.get("/workflow/wf_deadbeef/status")
    assert response.status_code == 404


def test_unknown_route_is_json_not_html(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.is_json and response.get_json()["status"] == 404


def test_list_filters_by_state_and_rejects_unknown_states(client):
    first = client.post("/workflow", json=VALID).get_json()["workflow_id"]
    second = client.post("/workflow", json={**VALID, "feature": "loans"}).get_json()["workflow_id"]
    listed = client.get("/workflows").get_json()
    assert {w["workflow_id"] for w in listed} == {first, second}
    assert client.get("/workflows?state=created").get_json()[0]["workflow_id"] in (first, second)
    assert client.get("/workflows?state=accepted").get_json() == []
    response = client.get("/workflows?state=bogus")
    assert response.status_code == 400 and "states" in response.get_json()


def test_workflows_survive_a_restart(tmp_path):
    first = create_app(data_dir=tmp_path / "data", audit_dir=tmp_path / "audit")
    workflow_id = first.test_client().post("/workflow", json=VALID).get_json()["workflow_id"]
    assert (tmp_path / "data" / f"{workflow_id}.json").exists()

    second = create_app(data_dir=tmp_path / "data", audit_dir=tmp_path / "audit")
    reloaded = second.test_client().get(f"/workflow/{workflow_id}")
    assert reloaded.status_code == 200 and reloaded.get_json()["request"] == VALID["request"]
    assert second.test_client().get("/health").get_json()["workflows"] == 1


def test_unexpected_errors_are_structured_json(app, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    monkeypatch.setattr(app.extensions["multi_agent"]["store"], "create", boom)
    response = app.test_client().post("/workflow", json=VALID)
    assert response.status_code == 500
    assert response.get_json() == {"error": "RuntimeError: disk full", "status": 500}
