"""Tests for the shared Multi-Agent Server.

Everything runs against a Flask test client with temporary data and audit
directories, an inline executor (stages run before POST /workflow answers), a
scripted model and a fake feature API, so no server, provider, API key or
running feature backend is needed.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("flask")

from agentic import llm  # noqa: E402
from agentic.llm import LLMUnavailable  # noqa: E402
from multi_agent_server import catalogue, config, evidence, metrics, review as review_cli, run as run_cli, terminal  # noqa: E402
from multi_agent_server import validate  # noqa: E402
from multi_agent_server.agents import planner, reviewer, worker  # noqa: E402
from multi_agent_server.contracts import (  # noqa: E402
    ContractError, allowed_numbers, numbers_in_text, parse_json_object, ungrounded_numbers, validate_plan,
    validate_result, validate_review,
)
from multi_agent_server.http import FetchResult, UpstreamError  # noqa: E402
from multi_agent_server.models import State  # noqa: E402
from multi_agent_server.orchestrator import InlineExecutor  # noqa: E402
from multi_agent_server import server as server_module  # noqa: E402
from multi_agent_server.server import create_app  # noqa: E402

CONTEXT = {"customer_id": 1, "month": 9, "year": 2026}
VALID = {"feature": "budgeting", "request": "review this month's budget performance", "context": CONTEXT}

GOOD_PLAN = {
    "objective": "Compare September 2026 spending with the budgets set for customer 1",
    "tasks": [
        {"id": "t1", "kind": "api", "title": "Budget summary", "endpoint": "/api/budgets/summary",
         "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "totals and per-category status"},
        {"id": "t2", "kind": "api", "title": "Spending by category", "endpoint": "/api/transactions/spending",
         "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "spend per category"},
        {"id": "t3", "kind": "analysis", "title": "Judge the month", "depends_on": ["t1", "t2"],
         "instruction": "Name the categories over budget and the overall position", "evidence": "findings"},
    ],
    "success_criteria": ["Every over-budget category in the summary is named"],
    "limitations": [],
}
BAD_PLAN = {
    "objective": "Look at another customer",
    "tasks": [
        {"id": "t1", "kind": "api", "title": "Nope", "endpoint": "/api/customers", "params": {}, "evidence": "x"},
        {"id": "t2", "kind": "api", "title": "Wrong customer", "endpoint": "/api/budgets/summary",
         "params": {"customer_id": 2, "month": 9, "year": 2026}, "evidence": "x"},
    ],
    "success_criteria": ["something"],
}


SUMMARY_PAYLOAD = {
    "customer_id": 1, "month": 9, "year": 2026, "spending_source": "transactions-api",
    "budgets": [
        {"category": "Groceries", "monthly_limit": 600.0, "spent": 645.0, "remaining": -45.0,
         "percent_used": 107.5, "status": "OVER_BUDGET", "over_budget": True, "over_by": 45.0},
        {"category": "Dining Out", "monthly_limit": 300.0, "spent": 411.0, "remaining": -111.0,
         "percent_used": 137.0, "status": "OVER_BUDGET", "over_budget": True, "over_by": 111.0},
        {"category": "Transport", "monthly_limit": 250.0, "spent": 218.0, "remaining": 32.0,
         "percent_used": 87.2, "status": "NEAR_LIMIT", "over_budget": False, "over_by": 0.0},
    ],
    "totals": {"total_limit": 1150.0, "total_spent": 1274.0, "total_remaining": -124.0,
               "percent_used": 110.8, "over_budget_count": 2},
    "over_budget_categories": ["Groceries", "Dining Out"],
    "unbudgeted_spending": [{"category": "Entertainment", "spent": 89.0}],
}
SPENDING_PAYLOAD = {
    "customer_id": 1, "month": 9, "year": 2026, "spending_source": "transactions-api",
    "totals_by_category": {"Groceries": 645.0, "Dining Out": 411.0, "Transport": 218.0, "Entertainment": 89.0},
    "transaction_count": 21,
}
GOOD_RESULT = {
    "findings": [
        {"task_id": "t3",
         "statement": "Groceries is over budget by $45.00 (107.5% used) and Dining Out by $111.00 (137.0% used); "
                      "total spent $1,274.00 against limits of $1,150.00.",
         "evidence": ["t1", "t2"]},
    ],
    "answer": "Two categories went over budget in September 2026: Groceries by $45.00 and Dining Out by $111.00. "
              "Total spending was $1,274.00 against limits of $1,150.00 across 21 transactions.",
    "gaps": [],
}
GOOD_REVIEW = {
    "verdict": "accept",
    "summary": "The findings name both over-budget categories with figures that match the evidence and the answer follows from them.",
    "criteria": [{"index": 1, "met": True, "note": "Groceries and Dining Out are both named, matching over_budget_categories in t1"}],
    "defects": [],
    "risks": ["Spending figures come from the source the budgeting service reports, which the human should confirm"],
    "revision_notes": [],
}
REVISE_REVIEW = {
    "verdict": "revise",
    "summary": "The answer does not say how far over budget the total is.",
    "criteria": [{"index": 1, "met": False, "note": "The categories are named but the total overspend from t1 is missing"}],
    "defects": [{"severity": "high", "about": "answer", "note": "The total remaining figure in t1 is not reported"}],
    "risks": [],
    "revision_notes": ["State the total remaining figure from t1 in the answer"],
}
BAD_RESULT = {
    "findings": [{"task_id": "t3", "statement": "You spent $9,999.00 on groceries.", "evidence": ["t2"]}],
    "answer": "Spending was $9,999.00.",
    "gaps": [],
}


class FakeAPI:
    """Stands in for the feature backends: canned JSON per path, or a service that is down."""

    def __init__(self):
        self.payloads = {"/api/budgets/summary": SUMMARY_PAYLOAD, "/api/transactions/spending": SPENDING_PAYLOAD}
        self.down: set[str] = set()
        self.fail_after: int | None = None          # calls answered before the service "dies"
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, base_url, path, params=None):
        self.calls.append((base_url, path, dict(params or {})))
        url = f"{base_url.rstrip('/')}{path}"
        died = self.fail_after is not None and len(self.calls) > self.fail_after
        if path in self.down or died or base_url.startswith(validate.UNREACHABLE_URL):
            raise UpstreamError(f"connection refused at {url} - is the service running?")
        return FetchResult(url=url, status_code=200, payload=self.payloads.get(path, []), duration_seconds=0.012)


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(evidence, "fetch", fake)
    return fake


class ScriptedAsk:
    """Answers in order (repeating the last one, or cycling) and records every prompt."""

    def __init__(self, *answers, cycle=False):
        self.answers = list(answers)
        self.cycle = cycle
        self.calls: list[dict] = []

    def __call__(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        if self.cycle:
            answer = self.answers[(len(self.calls) - 1) % len(self.answers)]
        else:
            answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def make_app(tmp_path, ask, **kwargs):
    application = create_app(data_dir=tmp_path / "data", audit_dir=tmp_path / "audit",
                             executor=InlineExecutor(), ask=ask, **kwargs)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def ask():
    return ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True)


@pytest.fixture
def app(tmp_path, ask, api):
    return make_app(tmp_path, ask)


@pytest.fixture
def client(app):
    return app.test_client()


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _audit(tmp_path):
    return (_lines(tmp_path / "audit" / "workflow_history.jsonl"),
            _lines(tmp_path / "audit" / "coordination_audit.jsonl"))


# ---------------------------------------------------------------- health

def test_health_reports_roles_models_pipeline_and_audit_paths(client):
    body = client.get("/health").get_json()
    assert body["service"] == "multi-agent-server" and body["status"] == "running"
    assert body["roles"] == ["planner", "worker", "reviewer"]
    assert set(body["models"]) == {"planner", "worker", "reviewer"}
    assert body["features"] == list(config.FEATURES)
    assert body["pipeline"] == ["planner", "worker", "reviewer", "human"]
    assert body["max_revisions"] == 1 and body["pending"] == 0
    assert body["decisions"] == ["accept", "partially_accept", "reject"]
    assert body["auth"] == "open" and body["interrupted_on_start"] == []
    assert body["audit"]["workflow_history"].endswith("workflow_history.jsonl")
    assert body["audit"]["coordination_audit"].endswith("coordination_audit.jsonl")
    assert body["workflows"] == 0


# ---------------------------------------------------------------- request validation

@pytest.mark.parametrize("body, word", [
    ("[1]", "JSON object"),
    ({}, "feature"),
    ({"feature": "payments", "request": "x"}, "feature"),
    ({"feature": "budgeting"}, "request is required"),
    ({"feature": "budgeting", "request": "x" * 1001}, "1000 characters"),
    ({"feature": "budgeting", "request": "x", "context": [1]}, "context must be"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": 1, "month": 13}}, "context.month"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": "abc"}}, "context.customer_id"),
    ({"feature": "budgeting", "request": "x", "context": {"month": 9}}, "customer_id is required"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": 1, "ref": 9999}}, "context accepts only customer_id, month, year"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": True}}, "context.customer_id must be an integer"),
    ({"feature": "budgeting", "request": "x", "context": {"customer_id": 2.9}}, "context.customer_id must be an integer"),
    ({"feature": "budgeting", "request": ["not", "a", "string"], "context": {"customer_id": 1}}, "request must be a string"),
])
def test_bad_requests_are_400_with_a_reason(client, ask, body, word):
    if isinstance(body, str):
        response = client.post("/workflow", data=body, content_type="application/json")
    else:
        response = client.post("/workflow", json=body)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert word in response.get_json()["error"], response.get_json()
    assert ask.calls == []                        # nothing reached the model


def test_raw_json_edge_cases_are_400_not_500(client, ask):
    base = '"feature":"budgeting","context":{"customer_id":1,"month":9,"year":2026}'
    for body, word in (
        ('{' + base + ',"request":"budget \\udc00 check"}', "not valid text"),
        ('{"feature":"budgeting","request":"x","context":{"customer_id":Infinity}}', "must be an integer"),
        ('{"feature":"budgeting","request":"x","context":{"customer_id":1e999}}', "must be an integer"),
    ):
        response = client.post("/workflow", data=body, content_type="application/json")
        assert response.status_code == 400, (body, response.get_json())
        assert word in response.get_json()["error"], response.get_json()
    assert ask.calls == [] and client.get("/health").get_json()["workflows"] == 0
    assert client.get("/workflows").get_json() == []                        # no zombie workflow was registered


def test_oversized_bodies_are_refused_as_json(client, ask):
    huge = {"feature": "budgeting", "request": "x", "context": {"customer_id": 1, "month": 9, "year": 2026, "blob": "x" * 200_000}}
    response = client.post("/workflow", json=huge)
    assert response.status_code == 413 and response.is_json and response.get_json()["status"] == 413
    assert ask.calls == [] and client.get("/health").get_json()["workflows"] == 0


def test_unknown_feature_lists_the_allowed_ones(client):
    body = client.post("/workflow", json={"feature": "payments", "request": "x"}).get_json()
    assert body["allowed_features"] == list(config.FEATURES)


# ---------------------------------------------------------------- planner stage

def test_valid_run_goes_plan_work_review_to_the_human_gate(client, ask, api, tmp_path):
    response = client.post("/workflow", json=VALID)
    assert response.status_code == 202
    body = response.get_json()
    workflow_id = body["workflow_id"]
    assert workflow_id.startswith("wf_") and len(workflow_id) == 11
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert body["has_plan"] is True and body["has_result"] is True and body["has_review"] is True
    assert body["links"] == {"self": f"/workflow/{workflow_id}", "status": f"/workflow/{workflow_id}/status"}
    assert [s["role"] for s in body["stages"]] == ["planner", "worker", "reviewer", "human"]
    assert all(s["status"] == "completed" and s["fallback"] is False and s["attempt"] == 1 for s in body["stages"][:3])
    assert body["stages"][3] == {"role": "human", "attempt": 1, "status": "running", "model": "human",
                                 "duration_seconds": None, "fallback": False}
    assert body["revisions"] == 0 and body["decision"] is None and body["released"] is False

    # the Planner saw the request, the context and only the budgeting catalogue
    assert len(ask.calls) == 3
    call = ask.calls[0]
    assert "PLANNER" in call["system"] and "one JSON object" in call["system"]
    assert VALID["request"] in call["user"]
    assert json.dumps(CONTEXT, sort_keys=True) in call["user"]
    for entry in catalogue.endpoints("budgeting"):
        assert entry["path"] in call["user"]
    assert "/api/loans" not in call["user"]
    assert "rejected by the handoff contract" not in call["user"]
    assert call["model"] is None                  # no per-role override set

    plan_body = client.get(f"/workflow/{workflow_id}/plan").get_json()
    plan = plan_body["plan"]
    assert plan_body["state"] == State.AWAITING_HUMAN_REVIEW
    assert plan["objective"] == GOOD_PLAN["objective"]
    assert [t["id"] for t in plan["tasks"]] == ["t1", "t2", "t3"]
    assert plan["tasks"][0]["params"] == CONTEXT
    assert plan["tasks"][2]["depends_on"] == ["t1", "t2"]
    assert plan["meta"]["source"] == "model" and plan["meta"]["attempts"] == 1
    assert plan["meta"]["accepted_first_try"] is True and plan["meta"]["model"]

    # the Worker called the two planned endpoints over HTTP, with the plan's params
    assert [(path, params) for _base, path, params in api.calls] == [
        ("/api/budgets/summary", CONTEXT), ("/api/transactions/spending", CONTEXT)]
    assert all(base == config.SERVICE_URLS["budgeting"] for base, _p, _q in api.calls)

    result_body = client.get(f"/workflow/{workflow_id}/result").get_json()
    result = result_body["result"]
    assert result_body["state"] == State.AWAITING_HUMAN_REVIEW
    records = result["evidence"]
    assert [r["task_id"] for r in records] == ["t1", "t2"]
    assert records[0]["status"] == "ok" and records[0]["http_status"] == 200
    assert records[0]["url"].endswith("/api/budgets/summary") and records[0]["duration_seconds"] == 0.012
    assert records[0]["summary"]["budget_count"] == 3
    assert records[0]["summary"]["over_budget_categories"] == ["Groceries", "Dining Out"]
    assert records[0]["summary"]["totals"]["total_spent"] == 1274.0
    # derived figures a person asks for are computed by the server, so the Worker can quote them
    assert records[0]["summary"]["total_over_by"] == 156.0
    assert records[0]["summary"]["most_over_budget"] == {"category": "Dining Out", "over_by": 111.0}
    assert records[0]["summary"]["most_spent"] == {"category": "Groceries", "spent": 645.0}
    assert records[1]["summary"]["total_spent"] == 1363.0 and records[1]["summary"]["transaction_count"] == 21
    assert records[1]["summary"]["top_category"] == {"category": "Groceries", "amount": 645.0}
    assert result["findings"] == GOOD_RESULT["findings"]
    assert result["answer"] == GOOD_RESULT["answer"] and result["gaps"] == []
    assert result["meta"]["source"] == "model" and result["meta"]["attempts"] == 1 and result["meta"]["attempt"] == 1

    # the Worker's prompt carried the plan's analysis task, the criteria and the evidence, nothing else to do
    work = ask.calls[1]
    assert "WORKER" in work["system"] and "nothing else" in work["system"]
    assert VALID["request"] in work["user"] and GOOD_PLAN["objective"] in work["user"]
    assert GOOD_PLAN["success_criteria"][0] in work["user"]
    assert "t3 \"Judge the month\" (depends on t1, t2)" in work["user"]
    assert "t1 GET /api/budgets/summary" in work["user"] and "\"over_budget_categories\"" in work["user"]
    assert "HTTP 200" in work["user"] and work["max_tokens"] == worker.MAX_TOKENS

    # the Reviewer saw the plan's criteria, the findings, the answer, the evidence and the server's checks
    judge = ask.calls[2]
    assert "REVIEWER" in judge["system"] and "Role boundary" in judge["system"]
    assert "1. " + GOOD_PLAN["success_criteria"][0] in judge["user"]
    assert "- t3 (evidence t1, t2): " + GOOD_RESULT["findings"][0]["statement"] in judge["user"]
    assert GOOD_RESULT["answer"] in judge["user"]
    assert "t1 GET /api/budgets/summary" in judge["user"] and "\"over_budget_categories\"" in judge["user"]
    assert "- evidence_ok: 2" in judge["user"] and "- result_source: \"model\"" in judge["user"]
    assert "- max_revisions: 1" in judge["user"] and "rejected by the handoff contract" not in judge["user"]

    review_body = client.get(f"/workflow/{workflow_id}/review").get_json()
    review = review_body["review"]
    assert review_body["state"] == State.AWAITING_HUMAN_REVIEW and review_body["revisions"] == 0
    assert review["verdict"] == "accept" and review["escalated"] is False
    assert review["criteria"] == GOOD_REVIEW["criteria"] and review["defects"] == []
    assert review["risks"] == GOOD_REVIEW["risks"] and review["revision_notes"] == []
    assert review["checks"]["evidence_ok"] == 2 and review["checks"]["result_source"] == "model"
    assert review["checks"]["spending_sources"] == ["transactions-api"]
    assert review["meta"]["source"] == "model" and review["meta"]["attempt"] == 1 and review["meta"]["attempts"] == 1

    full = client.get(f"/workflow/{workflow_id}").get_json()
    assert full["plan"] == plan and full["result"] == result and full["review"] == review and full["decision"] is None
    assert full["stages"][0]["output"]["task_count"] == 3
    assert full["stages"][1]["output"] == {"tasks_total": 2, "tasks_ok": 2, "tasks_failed": 0,
                                           "finding_count": 1, "source": "model", "calls": 1}
    assert full["stages"][2]["output"] == {"verdict": "accept", "defects": 0, "risks": 1, "source": "model", "calls": 1}
    assert all(s["duration_seconds"] is not None for s in full["stages"][:3])
    assert full["final_response"] is None

    # the completion gate in HTTP form: no response before the decision
    withheld = client.get(f"/workflow/{workflow_id}/response")
    assert withheld.status_code == 409
    assert withheld.get_json()["awaiting_decision"] is True and withheld.get_json()["state"] == State.AWAITING_HUMAN_REVIEW
    assert withheld.get_json()["links"]["decision"] == f"/workflow/{workflow_id}/decision"
    pending = client.get("/workflows/pending").get_json()
    assert pending["count"] == 1 and pending["options"] == ["accept", "partially_accept", "reject"]
    assert pending["workflows"][0]["workflow_id"] == workflow_id and pending["workflows"][0]["review_verdict"] == "accept"
    assert pending["workflows"][0]["request"] == VALID["request"] and pending["workflows"][0]["escalated"] is False
    assert client.get("/health").get_json()["pending"] == 1

    history, coordination = _audit(tmp_path)
    assert [r["event"] for r in history] == [
        "workflow_created", "state_changed", "stage_started", "stage_completed", "state_changed",
        "state_changed", "stage_started", "stage_completed", "state_changed",
        "state_changed", "stage_started", "stage_completed", "state_changed",
        "stage_started", "state_changed"]                    # the human stage opens before the gate state
    assert [(r["detail"].get("from"), r["detail"].get("to")) for r in history if r["event"] == "state_changed"] == [
        ("created", "planning"), ("planning", "planned"), ("planned", "working"), ("working", "executed"),
        ("executed", "reviewing"), ("reviewing", "reviewed"), ("reviewed", "awaiting_human_review")]
    started = [r for r in history if r["event"] == "stage_started"]
    assert [r["role"] for r in started] == ["planner", "worker", "reviewer", "human"]
    assert all(r["model"] and r["detail"]["timeout_seconds"] > 0 for r in started)
    assert [r["decision"] for r in coordination] == [
        "request_accepted", "plan_accepted", "handoff", "result_accepted", "handoff", "verdict_recorded",
        "review_accepted", "handoff", "awaiting_decision"]
    assert coordination[7]["detail"] == {"from": "reviewer", "to": "human", "contract": "review", "verdict": "accept",
                                         "escalated": False, "open_defects": 0, "risks": 1}
    assert coordination[8]["detail"] == {"options": ["accept", "partially_accept", "reject"], "released": False}
    assert coordination[1]["detail"] == {"attempts": 1, "task_count": 3, "accepted_first_try": True}
    assert coordination[2]["detail"] == {"from": "planner", "to": "worker", "contract": "plan", "task_count": 3, "attempt": 1}
    assert coordination[3]["detail"] == {"attempt": 1, "calls": 1, "finding_count": 1, "accepted_first_try": True}
    assert coordination[4]["detail"] == {"from": "worker", "to": "reviewer", "contract": "result", "finding_count": 1, "attempt": 1}
    assert coordination[5]["detail"] == {"attempt": 1, "verdict": "accept", "calls": 1, "criteria_met": 1,
                                         "criteria_total": 1, "defects": 0, "accepted_first_try": True}
    assert coordination[6]["detail"]["completion_gate"] == "every criterion met, no high-severity defect"
    for record in history + coordination:
        assert record["workflow_id"] == workflow_id and record["ts"].endswith("+00:00")


def test_off_contract_plan_gets_one_correction(tmp_path, api):
    ask = ScriptedAsk(BAD_PLAN, GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "model" and plan["meta"]["attempts"] == 2
    assert plan["meta"]["accepted_first_try"] is False
    errors = plan["meta"]["rejections"][0]
    assert any("not in the budgeting catalogue" in e for e in errors)
    assert any("customer_id=2 does not match the context" in e for e in errors)

    assert len(ask.calls) == 4
    retry = ask.calls[1]["user"]
    assert "rejected by the handoff contract" in retry
    for error in errors:
        assert error in retry                     # the model is told exactly what to fix

    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination][:3] == ["request_accepted", "plan_rejected", "plan_accepted"]
    assert coordination[1]["detail"]["attempt"] == 1 and coordination[1]["detail"]["action"] == "retry"


def test_two_off_contract_plans_fall_back_and_say_so(tmp_path, api):
    # the fallback plan carries two success criteria, so the scripted review judges both
    two_criteria = {**GOOD_REVIEW, "criteria": [{"index": 1, "met": True, "note": "t1 and t2 answered"},
                                                {"index": 2, "met": True, "note": "t3 cites t1 and t2"}]}
    ask = ScriptedAsk(BAD_PLAN, "not even json", GOOD_RESULT, two_criteria)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert body["stages"][0] == {**body["stages"][0], "status": "completed", "fallback": True}
    assert [s["fallback"] for s in body["stages"][1:3]] == [False, False]  # Worker and Reviewer ran the fallback plan normally
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback"
    assert "rejected by the contract 2 times" in plan["meta"]["fallback_reason"]
    assert len(plan["meta"]["rejections"]) == 2
    assert plan["limitations"] == ["Fallback plan built from the catalogue defaults, not from the request wording"]
    assert [t["endpoint"] for t in plan["tasks"] if t["kind"] == "api"] == ["/api/budgets/summary", "/api/transactions/spending"]
    assert plan["tasks"][-1]["kind"] == "analysis" and plan["tasks"][-1]["depends_on"] == ["t1", "t2"]

    history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination][:4] == ["request_accepted", "plan_rejected", "plan_rejected", "fallback_applied"]
    assert coordination[2]["detail"]["action"] == "fallback"
    assert coordination[3]["detail"]["stage"] == "planner"
    completed = next(r for r in history if r["event"] == "stage_completed")
    assert completed["detail"]["fallback"] is True and completed["detail"]["source"] == "fallback"


def test_unavailable_model_falls_back_without_failing(tmp_path, api):
    ask = ScriptedAsk(LLMUnavailable("GEMINI_API_KEY is not set"))
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert [s["fallback"] for s in body["stages"]] == [True, True, True, False]   # the human gate is never a fallback
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback"
    assert "model unavailable: GEMINI_API_KEY is not set" in plan["meta"]["fallback_reason"]
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["source"] == "fallback" and "GEMINI_API_KEY" in result["meta"]["fallback_reason"]
    assert [r["status"] for r in result["evidence"]] == ["ok", "ok"]     # evidence is real even without a model
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == reviewer.ESCALATE and review["escalated"] is True
    assert review["escalation_reason"].startswith("model unavailable: GEMINI_API_KEY is not set")
    assert review["criteria"] == [{"index": 1, "met": None, "note": "not evaluated"}, {"index": 2, "met": None, "note": "not evaluated"}]
    assert review["risks"][0].startswith("Review not performed") and "no model analysis" in review["risks"][1]
    assert body["revisions"] == 0                                         # nothing to send back without a verdict
    _history, coordination = _audit(tmp_path)
    fallbacks = [r for r in coordination if r["decision"] == "fallback_applied"]
    assert [r["detail"]["stage"] for r in fallbacks] == ["planner", "worker", "reviewer"]
    assert all("GEMINI_API_KEY" in r["detail"]["reason"] for r in fallbacks)
    escalated = next(r for r in coordination if r["decision"] == "escalated_to_human")
    assert "GEMINI_API_KEY" in escalated["detail"]["reason"]


def test_slow_stages_are_timed_out_and_fall_back(tmp_path, api):
    def slow(system_prompt, user_prompt, **kwargs):
        time.sleep(0.5)
        return json.dumps(GOOD_PLAN)
    client = make_app(tmp_path, slow, stage_timeout=0.05).test_client()
    assert client.get("/health").get_json()["stage_timeout_seconds"] == 0.05
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert [(s["status"], s["fallback"]) for s in body["stages"]] == [("timed_out", True)] * 3 + [("running", False)]
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback" and "planner did not answer within 0.05s" in plan["meta"]["fallback_reason"]
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert "worker analysis did not answer within 0.05s" in result["meta"]["fallback_reason"]
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == reviewer.ESCALATE and "reviewer did not answer within 0.05s" in review["escalation_reason"]
    history, coordination = _audit(tmp_path)
    assert [r["event"] for r in history].count("stage_timed_out") == 3
    assert [r["detail"]["stage"] for r in coordination if r["decision"] == "fallback_applied"] == ["planner", "worker", "reviewer"]


def test_unexpected_stage_error_fails_the_workflow_visibly(tmp_path):
    ask = ScriptedAsk(RuntimeError("prompt family missing"))
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.FAILED
    assert body["error"] == "RuntimeError: prompt family missing"
    assert body["stages"] == [{**body["stages"][0], "role": "planner", "status": "failed"}]   # no record left running
    history, coordination = _audit(tmp_path)
    assert [r["event"] for r in history][-3:] == ["stage_failed", "state_changed", "workflow_failed"]
    assert history[-3]["role"] == "planner" and history[-3]["detail"]["error"] == "RuntimeError: prompt family missing"
    assert history[-1]["event"] == "workflow_failed" and history[-1]["state"] == State.FAILED
    assert coordination[-1]["decision"] == "workflow_failed"
    assert client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"] is None
    assert client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"] is None
    assert client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"] is None


def test_per_role_model_override_reaches_the_call(tmp_path, monkeypatch, api):
    monkeypatch.setenv("MULTI_AGENT_PLANNER_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("MULTI_AGENT_WORKER_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("MULTI_AGENT_REVIEWER_MODEL", "gemini-2.5-pro-review")
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert [c["model"] for c in ask.calls] == ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-pro-review"]
    assert [s["model"].split("/ ")[1] for s in body["stages"][:3]] == ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-pro-review"]
    assert body["stages"][3]["model"] == "human"
    models = client.get("/health").get_json()["models"]
    assert models == {"planner": "gemini-2.5-pro", "worker": "gemini-2.5-flash", "reviewer": "gemini-2.5-pro-review"}


# ---------------------------------------------------------------- worker stage

def test_ungrounded_result_gets_one_correction(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, BAD_RESULT, GOOD_RESULT, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["stages"][1]["fallback"] is False
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["source"] == "model" and result["meta"]["attempts"] == 2
    assert result["meta"]["accepted_first_try"] is False
    errors = result["meta"]["rejections"][0]
    assert any("9999.00 is not in the evidence" in e for e in errors)
    assert len(ask.calls) == 4
    retry = ask.calls[2]["user"]
    assert "rejected by the handoff contract" in retry and "9999.00" in retry
    _history, coordination = _audit(tmp_path)
    decisions = [r["decision"] for r in coordination]
    assert decisions[3:5] == ["result_rejected", "result_accepted"]
    assert coordination[3]["detail"] == {"attempt": 1, "call": 1, "errors": errors, "action": "retry"}
    assert coordination[4]["detail"]["calls"] == 2


def test_two_bad_results_fall_back_to_findings_from_the_evidence(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, BAD_RESULT, "no json here", GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert body["stages"][1]["status"] == "completed" and body["stages"][1]["fallback"] is True
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["source"] == "fallback"
    assert "rejected by the contract 2 times" in result["meta"]["fallback_reason"]
    assert len(result["meta"]["rejections"]) == 2
    assert [f["task_id"] for f in result["findings"]] == ["t3"]
    assert result["findings"][0]["evidence"] == ["t1", "t2"]
    statement = result["findings"][0]["statement"]
    assert "t1 GET /api/budgets/summary" in statement and "budget_count 3" in statement
    assert "t2 GET /api/transactions/spending" in statement and "transaction_count 21" in statement
    assert "No model analysis is included" in result["answer"] and result["gaps"][0].startswith("No model analysis")
    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination][3:6] == ["result_rejected", "result_rejected", "fallback_applied"]
    assert coordination[5]["detail"]["stage"] == "worker"


def test_feature_api_down_is_a_structured_failure(tmp_path, api):
    api.down = {"/api/budgets/summary", "/api/transactions/spending"}
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.FAILED
    assert body["error"].startswith("worker: no feature API answered: budgeting service unavailable: connection refused at ")
    assert "/api/budgets/summary - is the service running?" in body["error"]
    assert body["stages"][1]["status"] == "failed" and body["stages"][1]["fallback"] is False
    assert len(ask.calls) == 1                           # no model call without evidence

    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["source"] == "blocked"
    assert [r["status"] for r in result["evidence"]] == ["error", "error"]
    assert all(r["url"].startswith(config.SERVICE_URLS["budgeting"]) and r["http_status"] is None
               for r in result["evidence"])
    assert result["findings"] == [] and result["answer"] == ""

    history, coordination = _audit(tmp_path)
    assert [r["event"] for r in history][-3:] == ["stage_failed", "state_changed", "workflow_failed"]
    failed = history[-3]
    assert failed["role"] == "worker" and failed["detail"]["tasks_failed"] == 2 and "connection refused" in failed["detail"]["error"]
    blocked = next(r for r in coordination if r["decision"] == "worker_blocked")
    assert blocked["detail"]["reason"] == "no feature API answered"
    assert len(blocked["detail"]["urls"]) == 2 and all(u.startswith("http") for u in blocked["detail"]["urls"])
    assert coordination[-1]["decision"] == "workflow_failed"


def test_partial_api_failure_continues_with_gaps(tmp_path, api):
    api.down = {"/api/transactions/spending"}
    only_t1 = {**GOOD_RESULT, "findings": [{**GOOD_RESULT["findings"][0], "evidence": ["t1"]}],
               "answer": "Groceries is over by $45.00 and Dining Out by $111.00 in September 2026."}
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, only_t1, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert [r["status"] for r in result["evidence"]] == ["ok", "error"]
    assert result["meta"]["attempts"] == 2
    first_errors = result["meta"]["rejections"][0]
    assert any("evidence task t2 did not succeed" in e for e in first_errors)
    assert result["findings"][0]["evidence"] == ["t1"]
    assert len(result["gaps"]) == 1 and result["gaps"][0].startswith("t2 /api/transactions/spending: budgeting service unavailable")
    full = client.get(f"/workflow/{body['workflow_id']}").get_json()
    assert full["stages"][1]["output"]["tasks_ok"] == 1 and full["stages"][1]["output"]["tasks_failed"] == 1
    assert "t2 GET /api/transactions/spending" in ask.calls[1]["user"] and "-> error: budgeting service unavailable" in ask.calls[1]["user"]
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["checks"]["evidence_failed"] == 1 and "- evidence_failed: 1" in ask.calls[3]["user"]


# ---------------------------------------------------------------- reviewer stage and revision cycle

def test_revise_sends_the_worker_back_once_with_the_notes(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW, GOOD_RESULT, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 1
    assert [(s["role"], s["attempt"]) for s in body["stages"]] == [
        ("planner", 1), ("worker", 1), ("reviewer", 1), ("worker", 2), ("reviewer", 2), ("human", 1)]
    assert len(ask.calls) == 5

    second_work = ask.calls[3]["user"]
    assert "The Reviewer sent the previous result back with these notes" in second_work
    assert "- State the total remaining figure from t1 in the answer" in second_work
    assert "rejected by the handoff contract" not in second_work
    assert "- revisions_so_far: 1" in ask.calls[4]["user"] and "- attempt: 2" in ask.calls[4]["user"]

    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()
    assert review["revisions"] == 1 and review["review"]["verdict"] == "accept"
    assert review["review"]["meta"]["attempt"] == 2 and review["review"]["escalated"] is False
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["attempt"] == 2
    full = client.get(f"/workflow/{body['workflow_id']}").get_json()
    assert full["stages"][2]["output"]["verdict"] == "revise" and full["stages"][2]["output"]["defects"] == 1
    assert full["stages"][4]["output"]["verdict"] == "accept"
    assert [(path, params) for _b, path, params in api.calls] == [
        ("/api/budgets/summary", CONTEXT), ("/api/transactions/spending", CONTEXT)] * 2   # evidence is re-collected

    history, coordination = _audit(tmp_path)
    assert [(r["detail"].get("from"), r["detail"].get("to")) for r in history if r["event"] == "state_changed"] == [
        ("created", "planning"), ("planning", "planned"), ("planned", "working"), ("working", "executed"),
        ("executed", "reviewing"), ("reviewing", "revising"), ("revising", "working"), ("working", "executed"),
        ("executed", "reviewing"), ("reviewing", "reviewed"), ("reviewed", "awaiting_human_review")]
    decisions = [r["decision"] for r in coordination]
    assert decisions == ["request_accepted", "plan_accepted", "handoff", "result_accepted", "handoff", "verdict_recorded",
                         "revision_requested", "handoff", "result_accepted", "handoff", "verdict_recorded", "review_accepted",
                         "handoff", "awaiting_decision"]
    requested = coordination[6]["detail"]
    assert requested == {"revision": 1, "max_revisions": 1, "notes": REVISE_REVIEW["revision_notes"],
                         "defects": REVISE_REVIEW["defects"]}
    assert coordination[7]["detail"] == {"from": "reviewer", "to": "worker", "contract": "plan + revision_notes",
                                         "task_count": 3, "attempt": 2}
    assert coordination[11]["detail"]["revisions"] == 1


def test_second_revise_escalates_to_the_human(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW, GOOD_RESULT, REVISE_REVIEW)   # the Reviewer keeps asking
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 1
    assert [(s["role"], s["attempt"]) for s in body["stages"]] == [
        ("planner", 1), ("worker", 1), ("reviewer", 1), ("worker", 2), ("reviewer", 2), ("human", 1)]
    assert len(ask.calls) == 5                                      # bounded: no third worker attempt
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == "revise" and review["escalated"] is True
    assert review["escalation_reason"] == "revision limit reached (1)"
    assert review["defects"] == REVISE_REVIEW["defects"] and review["revision_notes"] == REVISE_REVIEW["revision_notes"]
    _history, coordination = _audit(tmp_path)
    escalated = next(r for r in coordination if r["decision"] == "escalated_to_human")
    assert escalated["detail"] == {"reason": "revision limit reached (1)", "revisions": 1,
                                   "open_defects": REVISE_REVIEW["defects"], "notes": REVISE_REVIEW["revision_notes"]}
    assert [r["decision"] for r in coordination].count("revision_requested") == 1
    gate = coordination[-2]
    assert gate["decision"] == "handoff" and gate["detail"]["to"] == "human" and gate["detail"]["escalated"] is True
    assert client.get("/workflows/pending").get_json()["workflows"][0]["escalated"] is True


def test_failed_revision_keeps_the_first_result_and_escalates(tmp_path, api):
    api.fail_after = 2                                              # the API dies after the first attempt's two calls
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 1
    assert [(s["role"], s["attempt"], s["status"]) for s in body["stages"]] == [
        ("planner", 1, "completed"), ("worker", 1, "completed"), ("reviewer", 1, "completed"),
        ("worker", 2, "failed"), ("human", 1, "running")]
    assert len(ask.calls) == 3                                      # no analysis call without evidence
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["answer"] == GOOD_RESULT["answer"] and result["meta"]["attempt"] == 1   # the first result survives
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == "revise" and review["escalated"] is True
    assert review["escalation_reason"].startswith("revision attempt failed (no feature API answered")
    assert "the first result is kept for the human" in review["escalation_reason"]
    assert review["defects"] == REVISE_REVIEW["defects"]            # the human sees what the Reviewer wanted changed
    _history, coordination = _audit(tmp_path)
    decisions = [r["decision"] for r in coordination]
    assert "revision_failed" in decisions and "workflow_failed" not in decisions
    escalated = next(r for r in coordination if r["decision"] == "escalated_to_human")
    assert escalated["detail"]["reason"].startswith("revision attempt failed")
    assert client.get("/workflows/pending").get_json()["count"] == 1
    decided = client.post(f"/workflow/{body['workflow_id']}/decision", json={"decision": "accept"})
    assert decided.status_code == 200 and decided.get_json()["final_response"]["answer"] == GOOD_RESULT["answer"]


def test_zero_revisions_escalates_at_the_first_revise(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW)
    client = make_app(tmp_path, ask, max_revisions=0).test_client()
    assert client.get("/health").get_json()["max_revisions"] == 0
    body = client.post("/workflow", json=VALID).get_json()
    assert "- max_revisions: 0" in ask.calls[2]["user"]            # the Reviewer is told the limit in use
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 0
    assert [s["role"] for s in body["stages"]] == ["planner", "worker", "reviewer", "human"]
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["escalated"] is True and review["escalation_reason"] == "revision limit reached (0)"


def test_completion_gate_rejects_accept_with_unmet_criteria(tmp_path, api):
    gated = {**GOOD_REVIEW, "criteria": [{"index": 1, "met": False, "note": "not shown"}]}
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, gated, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 0
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == "accept" and review["meta"]["attempts"] == 2
    errors = review["meta"]["rejections"][0]
    assert any("verdict accept is not allowed while criteria [1] are unmet" in e for e in errors)
    assert "rejected by the handoff contract" in ask.calls[3]["user"] and errors[0] in ask.calls[3]["user"]
    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination][5:7] == ["review_rejected", "verdict_recorded"]
    assert coordination[5]["detail"]["action"] == "retry"


def test_two_bad_reviews_escalate_instead_of_inventing_a_verdict(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, "not json", {"verdict": "maybe"})
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW and body["revisions"] == 0
    assert body["stages"][2]["fallback"] is True and body["stages"][2]["status"] == "completed"
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == reviewer.ESCALATE and review["escalated"] is True
    assert review["escalation_reason"] == "review rejected by the contract 2 times"
    assert len(review["meta"]["rejections"]) == 2
    assert review["summary"].startswith("The Reviewer could not evaluate the result")
    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination][-6:-2] == ["review_rejected", "review_rejected", "fallback_applied", "escalated_to_human"]
    assert coordination[-4]["detail"]["stage"] == "reviewer"


def test_review_checks_flag_mock_spending_and_fallback_results(tmp_path, api):
    api.payloads = {"/api/budgets/summary": {**SUMMARY_PAYLOAD, "spending_source": "mock"},
                    "/api/transactions/spending": {**SPENDING_PAYLOAD, "spending_source": "mock"}}
    ask = ScriptedAsk(GOOD_PLAN, LLMUnavailable("quota exceeded"))
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["checks"]["spending_sources"] == ["mock"] and review["checks"]["result_source"] == "fallback"
    assert any("mock dataset" in r for r in review["risks"]) and any("no model analysis" in r for r in review["risks"])


@pytest.mark.parametrize("mutate, word", [
    (lambda r: r.update(verdict="maybe"), "verdict must be one of"),
    (lambda r: r.update(summary=""), "summary is required"),
    (lambda r: r.update(summary="Total $4,321.00 is wrong"), "summary: the number 4321.00 is not in the evidence"),
    (lambda r: r.update(criteria=[]), "missing [1]"),
    (lambda r: r.update(criteria=r["criteria"] * 2), "judged twice"),
    (lambda r: r["criteria"][0].update(index=5), "index must be between 1 and 1"),
    (lambda r: r["criteria"][0].update(met="yes"), "met must be true or false"),
    (lambda r: r.update(defects=[{"severity": "fatal", "note": "x"}]), "severity must be one of"),
    (lambda r: r.update(defects=[{"severity": "low", "note": ""}]), "note is required"),
    (lambda r: r.update(risks="none"), "risks must be a list"),
    (lambda r: r.update(verdict="revise", revision_notes=[]), "revise requires at least one revision note"),
    (lambda r: r.update(defects=[{"severity": "high", "about": "answer", "note": "misleading"}]), "not allowed with a high-severity defect"),
    (lambda r: r["criteria"][0].update(met=False), "not allowed while criteria [1] are unmet"),
    (lambda r: r.update(revision_notes=["Use $77.00 instead"], verdict="revise"), "77.00 is not in the evidence"),
])
def test_review_contract_rejects_bad_reviews_with_reasons(mutate, word):
    plan = validate_plan(json.loads(json.dumps(GOOD_PLAN)), "budgeting", CONTEXT)
    records = [
        {"task_id": "t1", "status": "ok", "endpoint": "/api/budgets/summary", "params": CONTEXT,
         "summary": evidence.summarise("/api/budgets/summary", SUMMARY_PAYLOAD, CONTEXT)},
        {"task_id": "t2", "status": "ok", "endpoint": "/api/transactions/spending", "params": CONTEXT,
         "summary": evidence.summarise("/api/transactions/spending", SPENDING_PAYLOAD, CONTEXT)},
    ]
    review = json.loads(json.dumps(GOOD_REVIEW))
    mutate(review)
    with pytest.raises(ContractError) as info:
        validate_review(review, plan, records)
    assert any(word in e for e in info.value.errors), info.value.errors
    clean = validate_review(json.loads(json.dumps(GOOD_REVIEW)), plan, records)
    assert clean["verdict"] == "accept" and clean["revision_notes"] == []
    revise = validate_review(json.loads(json.dumps(REVISE_REVIEW)), plan, records)
    assert revise["verdict"] == "revise" and revise["revision_notes"] == REVISE_REVIEW["revision_notes"]


def test_revision_notes_reach_the_worker_prompt(client, ask):
    workflow_id = client.post("/workflow", json=VALID).get_json()["workflow_id"]
    store = client.application.extensions["multi_agent"]["store"]
    workflow = store.get(workflow_id)
    system, user = worker.build_prompts(workflow, workflow.result["evidence"],
                                        worker._feedback_block("- Name the over-budget categories explicitly", ""))
    assert "The Reviewer sent the previous result back" in user
    assert "- Name the over-budget categories explicitly" in user
    assert "rejected by the handoff contract" not in user


# ---------------------------------------------------------------- human decision and final response

def _start(client):
    return client.post("/workflow", json=VALID).get_json()["workflow_id"]


def test_accept_releases_the_response_and_closes_the_audit(client, tmp_path):
    workflow_id = _start(client)
    response = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept", "by": "Bao"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == State.ACCEPTED and body["released"] is True
    assert body["decision"]["decision"] == "accept" and body["decision"]["by"] == "Bao" and body["decision"]["note"] == ""
    assert body["decision"]["decided_at"].endswith("+00:00")
    final = body["final_response"]
    assert final["released"] is True and final["answer"] == GOOD_RESULT["answer"]
    assert final["findings"] == GOOD_RESULT["findings"] and final["correction_note"] == ""
    assert final["review_verdict"] == "accept" and final["review_summary"] == GOOD_REVIEW["summary"]
    assert final["risks"] == GOOD_REVIEW["risks"] and final["gaps"] == []
    assert [e["endpoint"] for e in final["evidence_sources"]] == ["/api/budgets/summary", "/api/transactions/spending"]
    assert all(e["url"].startswith("http") and e["status"] == "ok" for e in final["evidence_sources"])
    assert final["decided_by"] == "Bao" and final["released_at"] == body["decision"]["decided_at"]
    assert final["revisions"] == 0 and len(final["models"]) == 1

    released = client.get(f"/workflow/{workflow_id}/response")
    assert released.status_code == 200 and released.get_json() == final
    assert client.get("/workflows/pending").get_json()["count"] == 0
    assert client.get(f"/workflow/{workflow_id}/status").get_json()["released"] is True

    full = client.get(f"/workflow/{workflow_id}").get_json()
    human = full["stages"][3]
    assert human["role"] == "human" and human["status"] == "completed" and human["duration_seconds"] is not None
    assert human["output"] == {"decision": "accept", "note": "", "by": "Bao", "released": True}

    history, coordination = _audit(tmp_path)
    tail = [r["event"] for r in history][-3:]
    assert tail == ["state_changed", "stage_completed", "workflow_completed"]       # persisted first, then audited
    assert history[-3]["detail"] == {"from": "awaiting_human_review", "to": "accepted"}
    assert history[-2]["role"] == "human" and history[-2]["detail"]["decision"] == "accept"
    assert history[-1]["detail"] == {"decision": "accept", "released": True, "revisions": 0, "stages": 4}
    assert [r["decision"] for r in coordination][-2:] == ["human_decision", "response_released"]
    assert coordination[-2]["actor"] == "human"
    assert coordination[-2]["detail"] == {"decision": "accept", "note": "", "by": "Bao", "review_verdict": "accept", "revisions": 0}
    assert coordination[-1]["detail"] == {"decision": "accept", "with_correction": False}

    again = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "reject"})
    assert again.status_code == 409 and again.get_json()["state"] == State.ACCEPTED


def test_partial_accept_releases_with_the_correction_note(client, tmp_path):
    workflow_id = _start(client)
    body = client.post(f"/workflow/{workflow_id}/decision",
                       json={"decision": "partially accept", "note": "Say the figures are from September only"}).get_json()
    assert body["state"] == State.PARTIALLY_ACCEPTED and body["released"] is True
    final = body["final_response"]
    assert final["decision"] == "partially_accept" and final["answer"] == GOOD_RESULT["answer"]
    assert final["correction_note"] == "Say the figures are from September only"
    assert final["decided_by"] == "api"
    _history, coordination = _audit(tmp_path)
    assert coordination[-1]["decision"] == "response_released"
    assert coordination[-1]["detail"] == {"decision": "partially_accept", "with_correction": True}


def test_reject_withholds_the_answer_but_keeps_the_trail(client, tmp_path):
    workflow_id = _start(client)
    body = client.post(f"/workflow/{workflow_id}/decision",
                       json={"decision": "reject", "note": "Figures come from mock data"}).get_json()
    assert body["state"] == State.REJECTED and body["released"] is False
    final = body["final_response"]
    assert final["released"] is False and final["answer"] is None and final["findings"] == [] and final["gaps"] == []
    assert final["correction_note"] == "Figures come from mock data" and final["released_at"] is None
    assert final["review_summary"] == GOOD_REVIEW["summary"]              # the trail stays readable
    assert len(final["evidence_sources"]) == 2
    response = client.get(f"/workflow/{workflow_id}/response")
    assert response.status_code == 200 and response.get_json()["released"] is False
    full = client.get(f"/workflow/{workflow_id}").get_json()
    assert full["result"]["answer"] == GOOD_RESULT["answer"]              # the record itself is not erased
    history, coordination = _audit(tmp_path)
    assert coordination[-1]["decision"] == "response_withheld"
    assert history[-1]["detail"]["released"] is False


@pytest.mark.parametrize("body, status, word", [
    ({"decision": "maybe"}, 400, "decision must be one of"),
    ({}, 400, "decision must be one of"),
    ({"decision": "accept", "note": "x" * 1001}, 400, "1000 characters"),
    ({"decision": "accept", "by": "x" * 101}, 400, "by must be 100 characters"),
    ({"decision": "accept", "note": {"a": [1, 2]}}, 400, "note must be a string"),
    ({"decision": "accept", "by": ["x"]}, 400, "by must be a string"),
    ({"decision": "partially_accept"}, 400, "needs a note saying what to correct"),
    ("[1]", 400, "JSON object"),
])
def test_bad_decisions_are_400_and_change_nothing(client, body, status, word):
    workflow_id = _start(client)
    if isinstance(body, str):
        response = client.post(f"/workflow/{workflow_id}/decision", data=body, content_type="application/json")
    else:
        response = client.post(f"/workflow/{workflow_id}/decision", json=body)
    assert response.status_code == status and word in response.get_json()["error"]
    assert response.get_json()["options"] == ["accept", "partially_accept", "reject"]
    assert client.get(f"/workflow/{workflow_id}/status").get_json()["state"] == State.AWAITING_HUMAN_REVIEW


def test_surrogate_note_cannot_half_apply_a_decision(client, tmp_path):
    workflow_id = _start(client)
    body = '{"decision":"accept","note":"looks fine \\ud83d","by":"Bao"}'
    response = client.post(f"/workflow/{workflow_id}/decision", data=body, content_type="application/json")
    assert response.status_code == 400 and "not valid text" in response.get_json()["error"]
    status = client.get(f"/workflow/{workflow_id}/status").get_json()
    assert status["state"] == State.AWAITING_HUMAN_REVIEW and status["decision"] is None
    assert client.get(f"/workflow/{workflow_id}/response").status_code == 409          # the gate still holds
    assert client.get("/workflows/pending").get_json()["count"] == 1
    _history, coordination = _audit(tmp_path)
    assert "human_decision" not in [r["decision"] for r in coordination]


def test_decision_is_restored_when_the_save_fails(client, tmp_path, monkeypatch):
    workflow_id = _start(client)
    store = client.application.extensions["multi_agent"]["store"]
    original = store.save

    def failing_save(workflow):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(store, "save", failing_save)
    response = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"})
    assert response.status_code == 500
    monkeypatch.setattr(store, "save", original)
    full = client.get(f"/workflow/{workflow_id}").get_json()
    assert full["state"] == State.AWAITING_HUMAN_REVIEW and full["decision"] is None and full["final_response"] is None
    assert full["stages"][-1]["role"] == "human" and full["stages"][-1]["status"] == "running"
    assert client.get(f"/workflow/{workflow_id}/response").status_code == 409
    _history, coordination = _audit(tmp_path)
    assert "human_decision" not in [r["decision"] for r in coordination]
    retry = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "reject", "note": "no"})
    assert retry.status_code == 200 and retry.get_json()["state"] == State.REJECTED
    assert [r["decision"] for r in _audit(tmp_path)[1]].count("human_decision") == 1


def test_decision_is_taken_back_on_disk_when_the_audit_cannot_be_written(client, tmp_path, monkeypatch):
    workflow_id = _start(client)
    ext = client.application.extensions["multi_agent"]
    original = ext["audit"].append_batch

    def failing_batch(history, coordination):
        raise OSError(28, "No space left on device")          # the disk is full for the whole attempt

    monkeypatch.setattr(ext["audit"], "append_batch", failing_batch)
    assert client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"}).status_code == 500
    monkeypatch.setattr(ext["audit"], "append_batch", original)
    on_disk = json.loads((tmp_path / "data" / f"{workflow_id}.json").read_text())
    assert on_disk["state"] == State.AWAITING_HUMAN_REVIEW and on_disk["final_response"] is None    # disk rolled back too
    assert client.get(f"/workflow/{workflow_id}/response").status_code == 409
    _history, coordination = _audit(tmp_path)
    assert "human_decision" not in [r["decision"] for r in coordination]
    # a restart sees the same thing and the decision can be made again
    second = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True)).test_client()
    assert second.get(f"/workflow/{workflow_id}/status").get_json()["state"] == State.AWAITING_HUMAN_REVIEW
    assert second.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"}).status_code == 200


def test_partial_audit_failure_leaves_a_marker_and_metrics_stay_sane(client, tmp_path, monkeypatch):
    workflow_id = _start(client)
    audit = client.application.extensions["multi_agent"]["audit"]
    original = audit.append_batch
    state = {"failed": False}

    def history_then_fail(history, coordination):
        """The history file takes the lines, then the coordination write fails, once."""
        if not state["failed"]:
            state["failed"] = True
            original(history, [])
            raise OSError(5, "Input/output error")
        return original(history, coordination)

    monkeypatch.setattr(audit, "append_batch", history_then_fail)
    assert client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"}).status_code == 500
    assert client.get(f"/workflow/{workflow_id}/status").get_json()["state"] == State.AWAITING_HUMAN_REVIEW
    retry = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "reject", "note": "changed my mind"})
    assert retry.status_code == 200 and retry.get_json()["state"] == State.REJECTED

    history, coordination = _audit(tmp_path)
    events = [(r["event"], r["detail"].get("to") or r["detail"].get("decision")) for r in history if r["workflow_id"] == workflow_id]
    assert ("decision_rolled_back", "accept") in events                      # the stray accept lines are explained
    assert events.index(("decision_rolled_back", "accept")) < events.index(("state_changed", "rejected"))
    assert [r["detail"]["decision"] for r in coordination if r["decision"] == "human_decision"] == ["reject"]
    assert any(r["decision"] == "decision_rolled_back" for r in coordination)

    body = client.get("/metrics").get_json()
    assert body["workflows"]["by_final_state"] == {"rejected": 1} and body["workflows"]["decided"] == 1
    assert body["counts"]["stages_finished"]["human"] == 1 and body["counts"]["stages_started"]["human"] == 1
    assert body["counts"]["rolled_back_decisions"] == 1 and body["human_decisions"] == {"reject": 1}


def test_non_ascii_token_or_header_is_401_not_500(tmp_path, api):
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True), api_token="s3crét").test_client()
    assert client.post("/workflow", json=VALID, headers={"Authorization": "Bearer s3cret"}).status_code == 401
    assert client.post("/workflow", json=VALID, headers={"Authorization": "Bearer s3crét"}).status_code == 202
    assert client.get("/workflows/pending", headers={"Authorization": "Bearer ✗"}).status_code == 401


def test_decision_on_a_failed_workflow_is_409(tmp_path, api):
    api.down = {"/api/budgets/summary", "/api/transactions/spending"}
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN)).test_client()
    workflow_id = _start(client)
    response = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"})
    assert response.status_code == 409 and response.get_json()["state"] == State.FAILED
    assert client.get(f"/workflow/{workflow_id}/response").status_code == 409
    assert client.get(f"/workflow/{workflow_id}/response").get_json()["awaiting_decision"] is False


def test_escalated_workflow_still_waits_for_the_human(tmp_path, api):
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW, GOOD_RESULT, REVISE_REVIEW)).test_client()
    workflow_id = _start(client)
    pending = client.get("/workflows/pending").get_json()["workflows"][0]
    assert pending["escalated"] is True and pending["review_verdict"] == "revise"
    body = client.post(f"/workflow/{workflow_id}/decision", json={"decision": "reject", "note": "not good enough"}).get_json()
    assert body["state"] == State.REJECTED and body["final_response"]["review_verdict"] == "revise"


def test_gate_records_are_written_before_a_decision_can_be(client, tmp_path):
    workflow_id = _start(client)
    client.post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"})
    _history, coordination = _audit(tmp_path)
    gate = [r for r in coordination if r["decision"] in ("handoff", "awaiting_decision", "human_decision")][-3:]
    assert [r["decision"] for r in gate] == ["handoff", "awaiting_decision", "human_decision"]
    # the gate records carry the waiting state; the decision record is written once the new state is on disk
    assert [r["state"] for r in gate] == [State.AWAITING_HUMAN_REVIEW, State.AWAITING_HUMAN_REVIEW, State.ACCEPTED]


def test_concurrent_decisions_cannot_both_succeed(client, tmp_path):
    workflow_id = _start(client)
    results = []
    barrier = threading.Barrier(2)

    def decide(choice):
        barrier.wait()
        response = client.post(f"/workflow/{workflow_id}/decision", json={"decision": choice, "by": choice})
        results.append((choice, response.status_code))

    threads = [threading.Thread(target=decide, args=(c,)) for c in ("accept", "reject")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(code for _c, code in results) == [200, 409]
    full = client.get(f"/workflow/{workflow_id}").get_json()
    winner = next(c for c, code in results if code == 200)
    assert full["decision"]["decision"] == winner and full["final_response"]["decision"] == winner
    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination].count("human_decision") == 1


def test_second_server_start_leaves_a_running_servers_data_alone(tmp_path, monkeypatch, capsys):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]

    def must_not_run(*args, **kwargs):
        raise AssertionError("create_app must not run while another server holds the port")

    try:
        assert server_module.port_in_use(port) is True
        monkeypatch.setattr(config, "PORT", port)
        monkeypatch.setattr(server_module, "create_app", must_not_run)
        assert server_module.main() == 1
        out = capsys.readouterr().out
        assert "already in use" in out and "Nothing was changed on disk" in out
    finally:
        listener.close()
    assert server_module.port_in_use(port) is False


def test_store_skips_files_that_are_not_workflows(tmp_path, api):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "wf_list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "data" / "wf_broken.json").write_text('{"workflow_id": "wf_broken"}', encoding="utf-8")
    (tmp_path / "data" / "wf_nojson.json").write_text("not json", encoding="utf-8")
    app = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True))
    assert app.test_client().get("/health").get_json()["workflows"] == 0


def test_interrupted_workflows_are_closed_on_restart(tmp_path, api):
    first = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True))
    waiting = first.test_client().post("/workflow", json=VALID).get_json()["workflow_id"]
    # forge a workflow that was mid-run when the process died: state working, worker stage still running
    store = first.extensions["multi_agent"]["store"]
    stuck = store.create("budgeting", "cut off", dict(CONTEXT))
    stuck.state = State.WORKING
    from multi_agent_server.models import StageRecord, now_iso
    stuck.stages.append(StageRecord(role="planner", attempt=1, started_at=now_iso(), finished_at=now_iso(), status="completed"))
    stuck.stages.append(StageRecord(role="worker", attempt=1, started_at=now_iso(), status="running"))
    store.save(stuck)

    second = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True))
    health = second.test_client().get("/health").get_json()
    assert health["interrupted_on_start"] == [stuck.workflow_id]
    reloaded = second.test_client().get(f"/workflow/{stuck.workflow_id}").get_json()
    assert reloaded["state"] == State.FAILED
    assert reloaded["error"] == "interrupted by a server restart while working"
    assert [s["status"] for s in reloaded["stages"]] == ["completed", "failed"]
    assert reloaded["stages"][1]["error"].startswith("interrupted by a server restart")
    # the workflow waiting for a human is untouched and can still be decided
    assert second.test_client().get(f"/workflow/{waiting}/status").get_json()["state"] == State.AWAITING_HUMAN_REVIEW
    assert second.test_client().post(f"/workflow/{waiting}/decision", json={"decision": "accept"}).status_code == 200
    _history, coordination = _audit(tmp_path)
    interrupted = [r for r in coordination if r["decision"] == "interrupted"]
    assert len(interrupted) == 1 and interrupted[0]["workflow_id"] == stuck.workflow_id
    assert any(r["decision"] == "workflow_failed" and r["workflow_id"] == stuck.workflow_id for r in coordination)


def test_bearer_token_guards_every_workflow_route_but_not_health(tmp_path, api):
    app = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True), api_token="s3cret")
    client = app.test_client()
    assert client.get("/health").get_json()["auth"] == "token"
    refused = client.post("/workflow", json=VALID)
    assert refused.status_code == 401 and "bearer token" in refused.get_json()["error"]
    assert client.get("/workflows/pending").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = client.post("/workflow", json=VALID, headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202
    adapter = terminal.FlaskClientAdapter(client, token="s3cret")
    status, pending = adapter.get("/workflows/pending")
    assert status == 200 and pending["count"] == 1
    lines = []
    assert review_cli.main(["--decision", "accept"], client=adapter, input_fn=Inputs(), out=lines.append) == 0
    assert "response released" in "\n".join(lines)


def test_http_client_sends_the_token_and_explains_a_401(monkeypatch):
    seen = {}

    class Response:
        status_code = 401
        def json(self):
            return {"error": "missing or invalid bearer token"}

    def fake_request(method, url, json=None, headers=None, timeout=None):
        seen.update(method=method, url=url, headers=headers)
        return Response()

    monkeypatch.setattr(terminal.requests, "request", fake_request)
    client = terminal.HttpClient("http://localhost:8300", token="abc")
    with pytest.raises(terminal.ServerUnavailable) as info:
        client.get("/workflows/pending")
    assert seen["headers"] == {"Authorization": "Bearer abc"} and "MULTI_AGENT_API_TOKEN" in str(info.value)
    assert terminal.HttpClient("http://localhost:8300", token="").token == ""


def test_watch_one_waits_for_the_gate_then_stops(client):
    workflow_id = _start(client)

    class SlowGate:
        """Reports the workflow as still working the first two times it is asked."""
        def __init__(self, inner):
            self.inner, self.polls = inner, 0
            self.base_url = inner.base_url
        def get(self, path):
            if path.endswith("/status") and self.polls < 2:
                self.polls += 1
                status, body = self.inner.get(path)
                return status, {**body, "state": "working"}
            return self.inner.get(path)
        def post(self, path, body):
            return self.inner.post(path, body)

    slept = []
    lines = []
    code = review_cli.main(["--watch", "0.01", "--id", workflow_id, "--decision", "accept"],
                           client=SlowGate(terminal.FlaskClientAdapter(client)), input_fn=Inputs(),
                           out=lines.append, sleep=slept.append)
    text = "\n".join(lines)
    assert code == 0 and slept == [0.01, 0.01]
    assert "waiting for the human gate" in text and "-> accepted; response released" in text
    lines = []
    assert review_cli.main(["--watch", "0.01", "--id", workflow_id], client=terminal.FlaskClientAdapter(client),
                           input_fn=Inputs(), out=lines.append, sleep=lambda s: None) == 0
    assert "is accepted; nothing to decide" in "\n".join(lines)
    lines = []
    assert review_cli.main(["--watch", "0.01", "--id", "wf_deadbeef"], client=terminal.FlaskClientAdapter(client),
                           input_fn=Inputs(), out=lines.append, sleep=lambda s: None) == 1


# ---------------------------------------------------------------- terminal runners

class Inputs:
    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, prompt):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


def test_review_runner_prompts_and_records_the_decision(client, tmp_path):
    workflow_id = _start(client)
    lines = []
    code = review_cli.main([], client=terminal.FlaskClientAdapter(client), input_fn=Inputs("x", "p", "Mention the period"),
                           out=lines.append)
    text = "\n".join(lines)
    flat = " ".join(text.split())                                      # the renderer wraps long lines
    assert code == 0
    assert "1 workflow(s) awaiting human review" in text
    assert workflow_id in text and VALID["request"] in flat
    assert "Plan:" in text and "Evidence:" in text and "Finding:" in text and "Answer:" in text and "Review:" in text
    assert GOOD_RESULT["answer"] in flat and "accept [source model, attempt 1, criteria met 1/1]" in flat
    assert "Please answer A, P, R or S" in text                       # the bad key was re-asked
    assert "-> partially_accepted; response released" in text
    assert "Correction: Mention the period" in flat
    status = client.get(f"/workflow/{workflow_id}/status").get_json()
    assert status["state"] == State.PARTIALLY_ACCEPTED and status["decision"]["by"] == "terminal"
    assert status["decision"]["note"] == "Mention the period"


def test_prompt_insists_on_a_note_for_partially_accept():
    lines = []
    decision, note = terminal.prompt_decision(Inputs("p", "", "Fix the month"), lines.append)
    assert (decision, note) == ("partially_accept", "Fix the month")
    assert "needs a note" in "\n".join(lines)
    assert terminal.prompt_decision(Inputs("a", ""), lines.append) == ("accept", "")
    with pytest.raises(terminal.InputClosed):                                   # stdin ran dry before the note
        terminal.prompt_decision(Inputs("p"), lines.append)
    with pytest.raises(terminal.InputClosed):
        terminal.prompt_decision(Inputs(), lines.append)


def test_review_runner_skip_and_flags(client):
    first = _start(client)
    lines = []
    assert review_cli.main([], client=terminal.FlaskClientAdapter(client), input_fn=Inputs("s"), out=lines.append) == 0
    assert "skipped" in "\n".join(lines)
    assert client.get(f"/workflow/{first}/status").get_json()["state"] == State.AWAITING_HUMAN_REVIEW

    lines = []
    code = review_cli.main(["--id", first, "--decision", "reject", "--note", "wrong month", "--by", "tutor"],
                           client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    assert code == 0 and "-> rejected; response withheld" in "\n".join(lines)
    status = client.get(f"/workflow/{first}/status").get_json()
    assert status["state"] == State.REJECTED and status["decision"] == {**status["decision"], "by": "tutor", "note": "wrong month"}

    lines = []
    code = review_cli.main(["--id", first], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    assert code == 0 and "nothing to decide" in "\n".join(lines)                # nothing wrong happened
    lines = []
    assert review_cli.main([], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append) == 0
    assert "0 workflow(s) awaiting human review" in "\n".join(lines)
    # a refused decision is an error exit; bad arguments are refused before any HTTP call
    second = _start(client)
    lines = []
    code = review_cli.main(["--id", second, "--decision", "accept", "--by", "x" * 101],
                           client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    assert code == 1 and "decision refused (400)" in "\n".join(lines)
    with pytest.raises(SystemExit) as info:
        review_cli.main(["--decision", "partially_accept"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    assert info.value.code == 2
    with pytest.raises(SystemExit):
        review_cli.main(["--watch", "0"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    with pytest.raises(SystemExit):
        run_cli.main(["--request", "x", "--poll", "-1"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    with pytest.raises(SystemExit):
        run_cli.main(["--request", "x", "--decision", "partially_accept"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)


def test_watch_mode_stops_when_stdin_is_closed_and_does_not_rerender_skips(client):
    first = _start(client)
    lines = []
    code = review_cli.main(["--watch", "0.01"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(),
                           out=lines.append, sleep=lambda s: None)
    text = "\n".join(lines)
    assert code == 0 and "stopped: stdin is closed" in text
    assert text.count(first) == 1                                             # rendered once, not every pass
    # a skipped workflow is not shown again while unchanged; the pass ends when input runs out
    slept = []
    lines = []
    def stop_after(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            raise KeyboardInterrupt
    code = review_cli.main(["--watch", "0.01"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs("s", "s", "s", "s"),
                           out=lines.append, sleep=stop_after)
    text = "\n".join(lines)
    assert code == 130 and text.count("skipped") == 1 and text.count("awaiting human review") == 1


def test_run_runner_reports_an_unreadable_workflow(client):
    class Missing:
        def __init__(self, inner):
            self.inner, self.base_url = inner, inner.base_url
        def get(self, path):
            if path.startswith("/workflow/wf_") and path.count("/") == 2:
                return 404, {"error": "gone"}
            return self.inner.get(path)
        def post(self, path, body):
            return self.inner.post(path, body)
    lines = []
    code = run_cli.main(["--request", "x", "--month", "9", "--year", "2026"], client=Missing(terminal.FlaskClientAdapter(client)),
                        input_fn=Inputs(), out=lines.append, sleep=lambda s: None)
    assert code == 1 and "could not read wf_" in lines[-1] and "gone" in lines[-1]


def test_run_runner_starts_follows_and_decides(client):
    lines = []
    code = run_cli.main(["--feature", "budgeting", "--request", "How did September go?", "--customer", "1",
                         "--month", "9", "--year", "2026"],
                        client=terminal.FlaskClientAdapter(client), input_fn=Inputs("a", ""), out=lines.append,
                        sleep=lambda s: None)
    text = "\n".join(lines)
    flat = " ".join(text.split())
    assert code == 0
    assert "Started wf_" in text and "following the stages" in text
    assert "  planner  attempt 1  completed  " in text and "  worker   attempt 1  completed  " in text
    assert "  reviewer attempt 1  completed  " in text
    assert "Awaiting your decision. The response is not released until you decide." in text
    assert "Decision accept: response released at" in text and GOOD_RESULT["answer"] in flat
    listed = client.get("/workflows?state=accepted").get_json()
    assert len(listed) == 1 and listed[0]["decision"]["by"] == "terminal"


def test_run_runner_reports_a_failed_workflow(tmp_path, api):
    api.down = {"/api/budgets/summary", "/api/transactions/spending"}
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN)).test_client()
    lines = []
    code = run_cli.main(["--request", "x", "--month", "9", "--year", "2026"], client=terminal.FlaskClientAdapter(client),
                        input_fn=Inputs(), out=lines.append, sleep=lambda s: None)
    text = "\n".join(lines)
    assert code == 2 and "workflow failed: worker: no feature API answered" in text
    assert "Error:" in text and "  worker   attempt 1  failed  " in text


def test_run_runner_can_leave_the_decision_for_later(client):
    lines = []
    code = run_cli.main(["--request", "x", "--month", "9", "--year", "2026"], client=terminal.FlaskClientAdapter(client),
                        input_fn=Inputs("s"), out=lines.append, sleep=lambda s: None)
    assert code == 0 and "decide later with: python -m multi_agent_server.review --id wf_" in "\n".join(lines)
    assert client.get("/workflows/pending").get_json()["count"] == 1


def test_runners_explain_an_unreachable_server(monkeypatch):
    lines = []
    code = review_cli.main(["--url", "http://127.0.0.1:9"], input_fn=Inputs(), out=lines.append)
    assert code == 1 and "cannot reach the Multi-Agent Server at http://127.0.0.1:9" in lines[-1]
    assert "python -m multi_agent_server.server" in lines[-1]
    lines = []
    code = run_cli.main(["--url", "http://127.0.0.1:9", "--request", "x"], input_fn=Inputs(), out=lines.append)
    assert code == 1 and "cannot reach" in lines[-1]


# ---------------------------------------------------------------- metrics and the validate script

def test_metrics_are_computed_from_the_audit_files_alone(client, tmp_path):
    first = _start(client)
    client.post(f"/workflow/{first}/decision", json={"decision": "accept"})
    second = _start(client)
    client.post(f"/workflow/{second}/decision", json={"decision": "reject", "note": "no"})
    body = client.get("/metrics").get_json()
    assert body["workflows"] == {"total": 2, "by_final_state": {"accepted": 1, "rejected": 1}, "decided": 2, "failed": 0}
    assert body["plan_acceptance_rate"] == 1.0 and body["worker_completion_rate"] == 1.0
    assert body["handoff_success_rate"] == 1.0 and body["reviewer_defect_yield"] == 0.0
    assert body["rework_ratio"] == 0.0 and body["escalation_rate"] == 0.0 and body["fallback_rate"] == 0.0
    assert body["human_acceptance_rate"] == 0.5 and body["human_decisions"] == {"accept": 1, "reject": 1}
    assert set(body["stage_seconds"]) == {"planner", "worker", "reviewer", "human"}
    assert body["end_to_end_seconds"]["to_human_gate"] is not None and body["end_to_end_seconds"]["to_decision"] is not None
    assert body["counts"]["handoffs"] == 6 and body["counts"]["stages_started"] == {"planner": 2, "worker": 2, "reviewer": 2, "human": 2}
    # the same numbers from a copy of the files, with no server involved
    history, coordination = _audit(tmp_path)
    assert metrics.compute(history, coordination) == {k: v for k, v in body.items() if k != "scope"} and body["scope"] == "all"
    # a filter narrows the metrics to named workflows
    one = client.get(f"/metrics?workflows={first}").get_json()
    assert one["scope"] == [first] and one["workflows"]["total"] == 1 and one["human_decisions"] == {"accept": 1}
    none = client.get("/metrics?workflows=").get_json()
    assert none["scope"] == [] and none["workflows"]["total"] == 0                # an empty filter is not "all"
    assert body["counts"]["handoff_anomalies"] == 0
    extra = metrics.compute(history, coordination + [{"ts": "2026-10-17T00:00:00+00:00", "workflow_id": first,
                                                      "state": "working", "decision": "handoff", "actor": "orchestrator", "detail": {}}])
    assert extra["counts"]["handoff_anomalies"] == 1 and extra["handoff_success_rate"] == 1.0


def test_metrics_reflect_revisions_fallbacks_and_failures(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW, GOOD_RESULT, GOOD_REVIEW, LLMUnavailable("quota"))
    client = make_app(tmp_path, ask).test_client()
    _start(client)                                                   # one revision, then accept verdict
    _start(client)                                                   # model unavailable: three fallbacks, escalated
    api.down = {"/api/budgets/summary", "/api/transactions/spending"}
    _start(client)                                                   # fails at the worker
    body = client.get("/metrics").get_json()
    assert body["workflows"]["total"] == 3 and body["workflows"]["failed"] == 1 and body["workflows"]["decided"] == 0
    assert body["rework_ratio"] == round(1 / 3, 3) and body["escalation_rate"] == round(1 / 3, 3)
    assert body["counts"]["revisions_requested"] == 1 and body["counts"]["escalations"] == 1
    assert body["counts"]["fallbacks"] == 4 and body["plan_acceptance_rate"] == round(1 / 3, 3)   # 3 in the 2nd, the planner in the 3rd
    assert body["worker_completion_rate"] == round(3 / 4, 3)        # two attempts + one fallback completed, one failed
    assert body["human_acceptance_rate"] is None and body["human_decisions"] == {}
    assert metrics.compute([], []) ["workflows"]["total"] == 0


def test_metrics_ignore_stray_lines_and_do_not_count_a_dead_worker_as_done(tmp_path, api, monkeypatch):
    def slow_fetch(base_url, path, params=None):
        time.sleep(0.3)
        return api(base_url, path, params)
    monkeypatch.setattr(evidence, "fetch", slow_fetch)
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True), stage_timeout=0.05).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.FAILED and "worker evidence did not answer" in body["error"]
    metrics_body = client.get("/metrics").get_json()
    assert metrics_body["workflows"]["failed"] == 1 and metrics_body["worker_completion_rate"] == 0.0
    with (tmp_path / "audit" / "workflow_history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('"stray string line"\n[1, 2]\n')
    assert client.get("/metrics").status_code == 200


def test_validate_passes_every_check_against_the_server(client, api, tmp_path, monkeypatch):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True)
    client.application.extensions["multi_agent"]["orchestrator"].ask = ask
    monkeypatch.setattr(validate, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(validate, "EVIDENCE_AUDIT_DIR", tmp_path / "evidence" / "multi_agent")
    records = validate.run_checks("flask://test", client=terminal.FlaskClientAdapter(client), ask=ask, sleep=lambda s: None)
    assert [(r.n, r.passed, r.skipped) for r in records] == [(n, True, False) for n in range(1, 10)]
    by_n = {r.n: r for r in records}
    assert by_n[2].detail["plan_source"] == "model" and by_n[2].detail["fallbacks"] == []
    assert by_n[2].detail["criteria_met"] == "1/1" and by_n[2].detail["spending_sources"] == ["transactions-api"]
    assert by_n[3].detail["status"] == 409
    assert by_n[4].detail["answer"] == GOOD_RESULT["answer"]
    assert by_n[5].detail["review_verdict"] == "accept"
    assert by_n[6].detail["human_decisions"] == ["accept", "reject"]
    assert by_n[7].detail["plan"]["rejected"] and by_n[7].detail["result"]["rejected"] and by_n[7].detail["review"]["rejected"]
    assert validate.UNREACHABLE_URL in by_n[8].detail["error"] and by_n[8].detail["worker_blocked"] is True
    assert by_n[8].detail["coordination"] == ["request_accepted", "plan_accepted", "handoff", "worker_blocked", "workflow_failed"]
    assert config.SERVICE_URLS["budgeting"] != validate.UNREACHABLE_URL                  # nothing global was touched
    assert by_n[8].detail["coordination"][1] == "plan_accepted"                             # the scripted plan was used
    assert by_n[9].detail["workflows"]["decided"] == 2 and by_n[9].detail["human_decisions"] == {"accept": 1, "reject": 1}
    assert sorted(by_n[9].detail["scope"]) == sorted(by_n[6].detail["workflow_ids"].values())
    ids = by_n[6].detail["workflow_ids"]
    assert set(ids) == {"accept", "reject"} and by_n[2].detail["workflow_ids"] == {"accept": ids["accept"]}

    written = validate.write_evidence("flask://test", records)
    report = json.loads(written[0].read_text())
    assert report["kind"] == "multi-agent-terminal-validation" and report["passed"] is True
    assert report["degraded_stages"] == [] and report["model_participation"] is True
    assert sorted(report["workflow_ids"]) == sorted(ids.values()) and len(report["records"]) == 9
    assert [p.name for p in written[1:]] == ["workflow_history.jsonl", "coordination_audit.jsonl"]
    snapshot = [json.loads(line) for line in written[1].read_text().splitlines()]
    assert {r["workflow_id"] for r in snapshot} == set(ids.values())
    assert "workflow_completed" in {r["event"] for r in snapshot}
    assert all(name in report["audit_snapshot"][i] for i, name in enumerate(("workflow_history.jsonl", "coordination_audit.jsonl")))


def test_validate_report_prints_the_tally_and_fails_when_unreachable(capsys):
    records = validate.run_checks("http://127.0.0.1:9")
    assert len(records) == 9 and records[0].passed is False and "cannot reach" in records[0].observed
    assert all(r.skipped and not r.passed and r.observed == "not run: check 1 failed" for r in records[1:])
    validate.print_report("http://127.0.0.1:9", records)
    out = capsys.readouterr().out
    assert "SmartBank Multi-Agent Server - terminal validation" in out
    assert "FAIL  1. server reachable" in out and "SKIP  9. coordination metrics" in out
    assert "0/1 checks passed, 8 skipped" in out
    assert validate.main(["--url", "http://127.0.0.1:9"]) == 1


def test_validate_refuses_evidence_from_a_dirty_tree(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(validate, "EVIDENCE_DIR", tmp_path / "evidence")            # never the repo's docs/evidence
    monkeypatch.setattr(validate, "EVIDENCE_AUDIT_DIR", tmp_path / "evidence" / "multi_agent")
    monkeypatch.setattr(validate, "_tree_is_dirty", lambda: True)
    assert validate.main(["--url", "http://127.0.0.1:9", "--evidence"]) == 2
    assert "refused: the working tree has uncommitted changes" in capsys.readouterr().out
    assert not (tmp_path / "evidence").exists()
    assert validate.main(["--url", "http://127.0.0.1:9", "--evidence", "--allow-dirty"]) == 1   # runs, server unreachable
    assert len(list((tmp_path / "evidence").glob("multi-agent-validation-*.json"))) == 1


def test_validate_fails_a_degraded_run_unless_allowed(client, api, tmp_path):
    client.application.extensions["multi_agent"]["orchestrator"].ask = ScriptedAsk(LLMUnavailable("no key"))
    records = validate.run_checks("flask://test", client=terminal.FlaskClientAdapter(client), sleep=lambda s: None)
    by_n = {r.n: r for r in records}
    assert by_n[2].passed is False and "DEGRADED: fallback in ['planner', 'worker', 'reviewer']" in by_n[2].observed
    assert "set GEMINI_API_KEY or pass --allow-fallback" in by_n[2].observed
    assert not any(r.skipped for r in records) and not all(r.passed for r in records)   # the gate checks still run; the record fails
    records = validate.run_checks("flask://test", client=terminal.FlaskClientAdapter(client), sleep=lambda s: None, allow_fallback=True)
    by_n = {r.n: r for r in records}
    assert by_n[2].passed is True and "allowed by --allow-fallback" in by_n[2].observed
    assert all(r.passed for r in records)


def test_validate_check_6_notices_a_missing_history(client, api, tmp_path):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW, cycle=True)
    client.application.extensions["multi_agent"]["orchestrator"].ask = ask
    history_path = tmp_path / "audit" / "workflow_history.jsonl"

    class DropsHistory:
        """After the second decision, deletes that workflow's history lines before check 6 reads them."""
        def __init__(self, inner):
            self.inner, self.base_url, self.decisions = inner, inner.base_url, 0
        def get(self, path):
            return self.inner.get(path)
        def post(self, path, body):
            status, payload = self.inner.post(path, body)
            if path.endswith("/decision"):
                self.decisions += 1
                if self.decisions == 2:
                    wid = path.split("/")[2]
                    kept = [l for l in history_path.read_text().splitlines() if f'"{wid}"' not in l]
                    history_path.write_text("\n".join(kept) + "\n")
            return status, payload
    records = validate.run_checks("flask://test", client=DropsHistory(terminal.FlaskClientAdapter(client)), ask=ask, sleep=lambda s: None)
    by_n = {r.n: r for r in records}
    assert by_n[6].passed is False and "MISSING" in by_n[6].observed
    assert any(gap.endswith(": workflow_created") for gap in by_n[6].detail["missing"])
    assert by_n[6].detail["workflow_ids"]["reject"] in by_n[6].observed


def test_validate_stops_cleanly_when_a_workflow_fails(tmp_path, api, monkeypatch):
    api.down = {"/api/budgets/summary", "/api/transactions/spending"}
    client = make_app(tmp_path, ScriptedAsk(GOOD_PLAN)).test_client()
    records = validate.run_checks("flask://test", client=terminal.FlaskClientAdapter(client), sleep=lambda s: None)
    assert [r.n for r in records] == list(range(1, 10)) and records[1].passed is False
    assert [r.skipped for r in records] == [False, False] + [True] * 7
    assert "failed" in records[1].observed and "no feature API answered" in records[1].observed
    failed_id = records[1].detail["workflow_ids"]["accept"]
    monkeypatch.setattr(validate, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(validate, "EVIDENCE_AUDIT_DIR", tmp_path / "evidence" / "multi_agent")
    written = validate.write_evidence("flask://test", records)
    report = json.loads(written[0].read_text())
    assert report["passed"] is False and report["workflow_ids"] == [failed_id]
    snapshot = [json.loads(line) for line in written[1].read_text().splitlines()]
    assert {r["workflow_id"] for r in snapshot} == {failed_id} and "workflow_failed" in {r["event"] for r in snapshot}


# ---------------------------------------------------------------- evidence summaries

def test_summaries_follow_the_mcp_tools_and_stay_bounded():
    accounts = evidence.summarise("/api/accounts", [
        {"account_id": 1, "account_number": "1234-5678", "balance": 5000.0, "status": "ACTIVE", "account_type": "SAVINGS"},
        {"account_id": 2, "account_number": "9999-0000", "balance": 12.5, "status": "FROZEN", "account_type": "CHEQUE"},
    ], {"customer_id": 1})
    assert accounts == {"customer_id": 1, "account_count": 2, "by_status": {"ACTIVE": 1, "FROZEN": 1},
                        "by_type": {"SAVINGS": 1, "CHEQUE": 1}}
    assert "balance" not in json.dumps(accounts) and "1234" not in json.dumps(accounts)

    transactions = evidence.summarise("/api/transactions", [
        {"amount": -50.0, "category": "Transport", "type": "Withdrawal", "date": "2026-09-01"},
        {"amount": -20.5, "category": "Transport", "type": "Withdrawal", "date": "2026-09-03"},
        {"amount": 2500.0, "category": "Salary", "type": "Deposit", "date": "2026-09-01"},
        {"amount": -9.99, "category": None, "type": "Withdrawal", "date": "2026-09-09"},
    ], {"customer_id": 1, "month": 9, "year": 2026})
    assert transactions["transaction_count"] == 4 and transactions["spending_count"] == 3
    assert transactions["totals_by_category"] == {"Transport": 70.5, "Uncategorised": 9.99}
    assert transactions["total_spent"] == 80.49
    assert (transactions["date_from"], transactions["date_to"]) == ("2026-09-01", "2026-09-30")

    alerts = evidence.summarise("/api/alerts", [{"severity": "HIGH", "status": "new"}, {"severity": "low", "status": "new"}], {"customer_id": 1})
    assert alerts["alert_count"] == 2 and alerts["by_severity"] == {"high": 1, "low": 1} and alerts["by_status"] == {"new": 2}

    loans = evidence.summarise("/api/loans", [{"loan_id": 7, "loan_type": "CAR", "requested_amount": 15000, "status": "APPROVED", "notes": "x"}], {"customer_id": 1})
    assert loans["loan_count"] == 1 and loans["loans"] == [{"loan_id": 7, "loan_type": "CAR", "requested_amount": 15000, "status": "APPROVED"}]

    rules = evidence.summarise("/api/rules", [{"rule_id": 1, "rule_name": "Large amount", "rule_type": "amount", "severity": "HIGH", "enabled": 1},
                                              {"rule_id": 2, "rule_name": "Velocity", "rule_type": "count", "severity": "MEDIUM", "enabled": 0}], {})
    assert rules["rule_count"] == 2 and rules["enabled_count"] == 1

    insights = evidence.summarise("/api/budgets/insights", [{"insight_id": 3, "budget_id": 1, "insight_text": "x" * 500,
                                                             "generated_at": "2026-09-30", "model_used": "gemini"}], {"customer_id": 1})
    assert insights["insight_count"] == 1 and len(insights["insights"][0]["insight_text"]) == evidence.MAX_TEXT_CHARS

    budgets = evidence.summarise("/api/budgets", [{"budget_id": 1, "customer_id": 1, "category": "Groceries", "monthly_limit": 600.0,
                                                   "month": 9, "year": 2026, "created_at": "2026-09-01"}], {"customer_id": 1})
    assert budgets == {"budget_count": 1, "budgets": [{"budget_id": 1, "category": "Groceries", "monthly_limit": 600.0, "month": 9, "year": 2026}]}

    assert evidence.summarise("/api/categories", [{"name": "Groceries", "description": "..."}, {"name": "Transport"}], {}) == \
        {"category_count": 2, "categories": ["Groceries", "Transport"]}
    generic = evidence.summarise("/api/unknown", {"status": "ok", "rows": [1, 2, 3], "note": "n" * 300, "flag": True}, {})
    assert generic == {"status": "ok", "rows_count": 3, "note": "n" * evidence.MAX_TEXT_CHARS, "flag": True}
    assert evidence.summarise("/api/unknown", [{"a": 1, "b": 2}, {"a": 3}], {}) == {"count": 2, "fields": ["a", "b"]}


def test_impossible_period_is_an_evidence_error_not_a_crash(api):
    record = evidence.collect_task({"id": "t1", "kind": "api", "endpoint": "/api/transactions",
                                    "params": {"customer_id": 1, "month": 13, "year": 2026}}, "transactions")
    assert record["status"] == "error" and record["error"].startswith("invalid period in the plan")
    assert api.calls == []


def test_period_params_become_a_date_range_for_the_transactions_api(api):
    record = evidence.collect_task({"id": "t1", "kind": "api", "endpoint": "/api/transactions",
                                    "params": {"customer_id": 1, "month": 9, "year": 2026, "category": "Transport"}}, "transactions")
    assert api.calls[-1] == (config.SERVICE_URLS["transactions"], "/api/transactions",
                             {"customer_id": 1, "category": "Transport", "date_from": "2026-09-01", "date_to": "2026-09-30"})
    assert record["params"] == {"customer_id": 1, "category": "Transport", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    assert record["status"] == "ok" and record["summary"]["transaction_count"] == 0


# ---------------------------------------------------------------- result contract and grounding

def test_number_grounding_helpers():
    assert numbers_in_text("$2,169.97 at 108% on t1 in 2026, -5 and 1.2k") == [
        (2169.97, 2), (108.0, 0), (2026.0, 0), (-5.0, 0), (1.2, 1)]
    allowed = {2169.97, 108.2, 2026.0, 9.0, 1.0}
    assert ungrounded_numbers("$2,169.97 at 108% on t1 in 2026, 9 of 12", allowed) == ["12"]   # 108 rounds from 108.2; 12 is unproven
    assert ungrounded_numbers("about $2,170 and 1.2k and 99%", allowed) == ["1.2", "99"]    # 2170 rounds from 2169.97
    assert ungrounded_numbers("no numbers here", set()) == []
    # a half is accepted whichever way it was rounded, and nothing further away
    assert ungrounded_numbers("113% or 112%", {112.5}) == [] and ungrounded_numbers("114%", {112.5}) == ["114"]
    assert ungrounded_numbers("$45.00 and $45.01", {45.0}) == ["45.01"]
    # sign is ignored: the API's total_remaining -124.0 is "$124.00 over" to a person
    assert ungrounded_numbers("You are $124.00 over your total budget", {-124.0}) == []
    # figures glued to a currency code or a word are still figures; task ids are not
    assert numbers_in_text("AUD1,200 and approx.9999 from t1 and t12") == [(1200.0, 0), (9999.0, 0)]
    assert ungrounded_numbers("USD9999 was spent", {120.5}) == ["9999"]
    # the day of a stored date string can be quoted
    from multi_agent_server.contracts import numbers_in_data
    assert {2026.0, 9.0, 30.0} <= numbers_in_data({"date_from": "2026-09-01", "date_to": "2026-09-30"})
    assert ungrounded_numbers("between 1 and 30 September 2026", {2026.0, 9.0, 1.0, 30.0}) == []


def test_allowed_numbers_include_context_plan_params_and_the_request():
    plan = {"tasks": [{"id": "t1", "kind": "api", "endpoint": "/api/transactions",
                       "params": {"customer_id": 1, "month": 9, "year": 2026}}]}
    # the transactions call turned the period into date strings, so the evidence itself carries no 2026
    evidence = [{"task_id": "t1", "status": "ok", "endpoint": "/api/transactions",
                 "params": {"customer_id": 1, "date_from": "2026-09-01", "date_to": "2026-09-30"},
                 "summary": {"transaction_count": 21, "total_spent": 120.5}}]
    allowed = allowed_numbers(plan, evidence, "Did I spend more than $500 in total?", {"customer_id": 1, "month": 9, "year": 2026})
    assert {2026.0, 9.0, 1.0, 500.0, 120.5, 21.0} <= allowed
    assert ungrounded_numbers("In September 2026 you spent $120.50, which is not more than $500.", allowed) == []
    assert ungrounded_numbers("In September 2026 you spent $999.00.", allowed) == ["999.00"]


def test_worker_may_quote_the_period_and_the_figure_the_person_typed(tmp_path, api):
    api.payloads["/api/transactions"] = [{"amount": -120.5, "category": "Groceries", "type": "Withdrawal", "date": "2026-09-03"}]
    plan = {**GOOD_PLAN, "tasks": [
        {"id": "t1", "kind": "api", "title": "Transactions", "endpoint": "/api/transactions",
         "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "totals"},
        {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "compare with $500", "evidence": "x"}]}
    result = {"findings": [{"task_id": "t2", "statement": "In September 2026 you spent $120.50 on Groceries, under the $500 you asked about.", "evidence": ["t1"]}],
              "answer": "No. In September 2026 your spending was $120.50, below $500.", "gaps": []}
    review = {**GOOD_REVIEW, "summary": "The September 2026 figure of $120.50 is in the evidence and the $500 comes from the request."}
    ask = ScriptedAsk(plan, result, review)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json={"feature": "transactions", "request": "Did I spend more than $500 in September 2026?",
                                          "context": CONTEXT}).get_json()
    assert body["state"] == State.AWAITING_HUMAN_REVIEW
    assert [s["fallback"] for s in body["stages"][:3]] == [False, False, False]          # no contract rejection anywhere
    stored = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert stored["meta"]["attempts"] == 1 and stored["answer"].startswith("No. In September 2026")
    assert stored["request_only_numbers"] == ["500"]                                   # named, not hidden
    assert '- request_only_numbers: ["500"]' in ask.calls[2]["user"]                   # the Reviewer is told
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["checks"]["request_only_numbers"] == ["500"]


def test_fabricated_small_counts_are_rejected_for_count_only_features(tmp_path, api):
    api.payloads["/api/alerts"] = [{"severity": "low", "status": "dismissed"}]
    plan = {**GOOD_PLAN, "tasks": [
        {"id": "t1", "kind": "api", "title": "Alerts", "endpoint": "/api/alerts", "params": {"customer_id": 1}, "evidence": "counts"},
        {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "count", "evidence": "x"}]}
    invented = {"findings": [{"task_id": "t2", "statement": "There are 7 alerts on your account, 5 high severity; 3 are confirmed.",
                              "evidence": ["t1"]}], "answer": "You have 7 alerts.", "gaps": []}
    honest = {"findings": [{"task_id": "t2", "statement": "There is 1 alert, severity low, status dismissed.", "evidence": ["t1"]}],
              "answer": "You have 1 alert, low severity, already dismissed.", "gaps": []}
    ask = ScriptedAsk(plan, invented, honest, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json={"feature": "fraud", "request": "How many fraud alerts do I have?", "context": {"customer_id": 1}}).get_json()
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["meta"]["attempts"] == 2 and result["answer"].startswith("You have 1 alert")
    errors = result["meta"]["rejections"][0]
    assert any("the number 7 is not in the evidence" in e for e in errors)
    assert any("the number 5 is not in the evidence" in e for e in errors) and any("the number 3 is not" in e for e in errors)


def test_gaps_and_defect_labels_are_grounded_too():
    plan = validate_plan(json.loads(json.dumps(GOOD_PLAN)), "budgeting", CONTEXT)
    records = [{"task_id": "t1", "status": "ok", "endpoint": "/api/budgets/summary", "params": CONTEXT,
                "summary": evidence.summarise("/api/budgets/summary", SUMMARY_PAYLOAD, CONTEXT)},
               {"task_id": "t2", "status": "ok", "endpoint": "/api/transactions/spending", "params": CONTEXT,
                "summary": evidence.summarise("/api/transactions/spending", SPENDING_PAYLOAD, CONTEXT)}]
    result = {**json.loads(json.dumps(GOOD_RESULT)), "gaps": ["Could not confirm the $9,999.00 transfer or the 3,500 missing rows"]}
    with pytest.raises(ContractError) as info:
        validate_result(result, plan, records)
    assert any("gap 1: the number 9999.00" in e for e in info.value.errors) and any("3500" in e for e in info.value.errors)
    review = {**json.loads(json.dumps(GOOD_REVIEW)), "defects": [{"severity": "low", "about": "the $8,888.00 overspend", "note": "wording"}]}
    with pytest.raises(ContractError) as info:
        validate_review(review, plan, records)
    assert any("8888.00" in e for e in info.value.errors)


def test_request_only_figures_reach_the_review_the_response_and_the_terminal(tmp_path, api):
    api.payloads["/api/transactions"] = [{"amount": -120.5, "category": "Groceries", "type": "Withdrawal", "date": "2026-09-03"}]
    plan = {**GOOD_PLAN, "tasks": [
        {"id": "t1", "kind": "api", "title": "Transactions", "endpoint": "/api/transactions",
         "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "totals"},
        {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "compare", "evidence": "x"}]}
    lax = {"findings": [{"task_id": "t2", "statement": "You spent $500 in September 2026.", "evidence": ["t1"]}],
           "answer": "You spent $500 and transferred $2,000 to account 4455.", "gaps": []}
    ask = ScriptedAsk(plan, lax, GOOD_REVIEW)
    client = make_app(tmp_path, ask).test_client()
    request = "Did I spend more than $500 in September 2026? Also confirm the $2,000 transfer to account 4455."
    body = client.post("/workflow", json={"feature": "transactions", "request": request, "context": CONTEXT}).get_json()
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == "accept"                                            # the lax model review stands
    assert any(r.startswith("Figures 500, 2000, 4455 come from the request") for r in review["risks"])   # but code adds the risk
    lines = []
    review_cli.main(["--decision", "accept"], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append)
    flat = " ".join("\n".join(lines).split())
    assert "Unproven: figures 500, 2000, 4455 come from the request, not from the evidence" in flat
    final = client.get(f"/workflow/{body['workflow_id']}/response").get_json()
    assert final["request_only_numbers"] == ["500", "2000", "4455"]
    assert any("come from the request" in r for r in final["risks"])


def test_plan_periods_are_bounded_even_without_a_context_period():
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["tasks"][0]["params"] = {"customer_id": 1, "month": 13, "year": 2026}
    with pytest.raises(ContractError) as info:
        validate_plan(plan, "budgeting", {"customer_id": 1})
    assert any("month=13 is out of range (1 to 12)" in e for e in info.value.errors)
    plan["tasks"][0]["params"] = {"customer_id": 0, "month": 9, "year": 99999}
    with pytest.raises(ContractError) as info:
        validate_plan(plan, "budgeting", {"customer_id": 1})
    assert any("customer_id=0" in e for e in info.value.errors) and any("year=99999" in e for e in info.value.errors)


def test_request_figure_stated_as_fact_is_flagged_for_the_reviewer(tmp_path, api):
    api.payloads["/api/transactions"] = [{"amount": -120.5, "category": "Groceries", "type": "Withdrawal", "date": "2026-09-03"}]
    plan = {**GOOD_PLAN, "tasks": [
        {"id": "t1", "kind": "api", "title": "Transactions", "endpoint": "/api/transactions",
         "params": {"customer_id": 1, "month": 9, "year": 2026}, "evidence": "totals"},
        {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "total", "evidence": "x"}]}
    wrong = {"findings": [{"task_id": "t2", "statement": "You spent $500 in September 2026.", "evidence": ["t1"]}],
             "answer": "You spent $500.", "gaps": []}
    ask = ScriptedAsk(plan, wrong, LLMUnavailable("quota"))
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json={"feature": "transactions", "request": "Did I spend more than $500 in September 2026?",
                                          "context": CONTEXT}).get_json()
    result = client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"]
    assert result["request_only_numbers"] == ["500"]                 # the contract let it through, but says so
    review = client.get(f"/workflow/{body['workflow_id']}/review").get_json()["review"]
    assert review["verdict"] == reviewer.ESCALATE
    assert any("Figures 500 come from the request, not from the evidence" in r for r in review["risks"])


@pytest.mark.parametrize("mutate, word", [
    (lambda r: r["findings"][0].update(task_id="t1"), "is not an analysis task"),
    (lambda r: r["findings"][0].update(statement=""), "statement is required"),
    (lambda r: r["findings"][0].update(statement="x" * 601), "600 characters"),
    (lambda r: r["findings"][0].update(evidence=[]), "at least one api task id"),
    (lambda r: r["findings"][0].update(evidence=["t9"]), "is not an api task"),
    (lambda r: r["findings"][0].update(statement="Spent $77.77 on food."), "77.77 is not in the evidence"),
    (lambda r: r.update(findings=[]), "analysis task t3 has no finding"),
    (lambda r: r.update(answer=""), "answer is required"),
    (lambda r: r.update(answer="Total $5,000.00."), "answer: the number 5000.00 is not in the evidence"),
    (lambda r: r.update(gaps="none"), "gaps must be a list"),
    (lambda r: r.update(findings="x"), "findings must be a list"),
])
def test_result_contract_rejects_bad_results_with_reasons(mutate, word):
    plan = validate_plan(json.loads(json.dumps(GOOD_PLAN)), "budgeting", CONTEXT)
    records = [
        {"task_id": "t1", "status": "ok", "endpoint": "/api/budgets/summary", "params": CONTEXT,
         "summary": evidence.summarise("/api/budgets/summary", SUMMARY_PAYLOAD, CONTEXT)},
        {"task_id": "t2", "status": "ok", "endpoint": "/api/transactions/spending", "params": CONTEXT,
         "summary": evidence.summarise("/api/transactions/spending", SPENDING_PAYLOAD, CONTEXT)},
    ]
    result = json.loads(json.dumps(GOOD_RESULT))
    mutate(result)
    with pytest.raises(ContractError) as info:
        validate_result(result, plan, records)
    assert any(word in e for e in info.value.errors), info.value.errors
    assert validate_result(json.loads(json.dumps(GOOD_RESULT)), plan, records)["answer"] == GOOD_RESULT["answer"]


# ---------------------------------------------------------------- contracts and catalogue

@pytest.mark.parametrize("mutate, word", [
    (lambda p: p.pop("objective"), "objective is required"),
    (lambda p: p.update(tasks=[]), "1 to 6 tasks"),
    (lambda p: p.update(tasks=p["tasks"][:1] * 7), "1 to 6 tasks"),
    (lambda p: p["tasks"][0].update(endpoint="/api/accounts"), "not in the budgeting catalogue"),
    (lambda p: p["tasks"][0]["params"].update(sql="SELECT *"), "not declared for /api/budgets/summary"),
    (lambda p: p["tasks"][0]["params"].update(month="september"), "month must be an integer"),
    (lambda p: p["tasks"][0]["params"].pop("year"), "requires year"),
    (lambda p: p["tasks"][2].pop("depends_on"), "must list depends_on"),
    (lambda p: p["tasks"][2].update(depends_on=["t9"]), "not defined before it"),
    (lambda p: p["tasks"][2].pop("instruction"), "need an instruction"),
    (lambda p: p.update(tasks=[p["tasks"][2] | {"depends_on": []}]), "must list depends_on"),
    (lambda p: p.update(tasks=[{"id": "t1", "kind": "analysis", "depends_on": ["t1"], "instruction": "x"}]), "at least one task must call an endpoint"),
    (lambda p: p.update(tasks=p["tasks"][:2]), "at least one analysis task is required"),
    (lambda p: p["tasks"][0]["params"].update(customer_id="--9"), "customer_id must be an integer"),
    (lambda p: p["tasks"][0]["params"].update(month="1e3"), "month must be an integer"),
    (lambda p: p.update(success_criteria=[]), "success_criteria needs"),
    (lambda p: p["tasks"].append(dict(p["tasks"][0])), "duplicate id"),
    (lambda p: p["tasks"][0].update(kind="shell"), "kind must be one of"),
])
def test_plan_contract_rejects_bad_plans_with_reasons(mutate, word):
    plan = json.loads(json.dumps(GOOD_PLAN))
    mutate(plan)
    with pytest.raises(ContractError) as info:
        validate_plan(plan, "budgeting", CONTEXT)
    assert any(word in e for e in info.value.errors), info.value.errors


def test_plan_contract_normalises_and_drops_unknown_keys():
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan["tasks"][0]["params"]["customer_id"] = "1"          # digit string is accepted as the integer
    plan["tasks"][0]["endpoint"] = "GET /api/budgets/summary"  # the verb copied from the catalogue listing is tolerated
    plan["tasks"][0]["notes"] = "ignored"
    plan["chatter"] = "ignored"
    clean = validate_plan(plan, "budgeting", CONTEXT)
    assert clean["tasks"][0]["params"]["customer_id"] == 1
    assert clean["tasks"][0]["endpoint"] == "/api/budgets/summary"
    assert "notes" not in clean["tasks"][0] and "chatter" not in clean
    assert clean["limitations"] == []


def test_parse_json_object_accepts_fenced_output():
    text = "```json\n" + json.dumps(GOOD_PLAN) + "\n```"
    assert parse_json_object(text)["objective"] == GOOD_PLAN["objective"]
    with pytest.raises(ContractError):
        parse_json_object("Sure! Here is the plan:")


@pytest.mark.parametrize("feature", config.FEATURES)
def test_fallback_plan_is_valid_for_every_feature(feature):
    plan = planner.fallback_plan(feature, CONTEXT)
    kinds = [t["kind"] for t in plan["tasks"]]
    assert kinds.count("api") >= 1 and kinds[-1] == "analysis"
    for task in plan["tasks"]:
        if task["kind"] == "api":
            assert catalogue.endpoint(feature, task["endpoint"]) is not None
            assert task["params"]["customer_id"] == 1
    # a context without a period still yields a valid plan (current month, as the APIs default)
    bare = planner.fallback_plan(feature, {"customer_id": 1})
    assert any(t["kind"] == "api" for t in bare["tasks"])


def test_catalogue_covers_every_feature_and_reads_well():
    assert set(catalogue.CATALOGUE) == set(config.FEATURES)
    text = catalogue.describe("budgeting")
    assert "GET /api/budgets/summary" in text and "month (required)" in text
    assert catalogue.describe("fraud").count("no parameters") == 1
    for feature in config.FEATURES:
        assert catalogue.default_endpoints(feature), feature
        for entry in catalogue.endpoints(feature):
            assert set(entry["required"]) <= set(entry["params"])


def test_prompt_family_exists_with_placeholders():
    root = Path(__file__).resolve().parent.parent / "prompts" / "_multi_agent"
    system = (root / "planner_system.txt").read_text(encoding="utf-8")
    task = (root / "planner_task.txt").read_text(encoding="utf-8")
    assert "PLANNER" in system and "Role boundary" in system
    for placeholder in ("${feature}", "${request}", "${context}", "${catalogue}", "${feedback}"):
        assert placeholder in task
    system = (root / "worker_system.txt").read_text(encoding="utf-8")
    task = (root / "worker_task.txt").read_text(encoding="utf-8")
    assert "WORKER" in system and "Role boundary" in system
    for placeholder in ("${feature}", "${request}", "${objective}", "${success_criteria}", "${analysis_tasks}", "${evidence}", "${feedback}"):
        assert placeholder in task
    system = (root / "reviewer_system.txt").read_text(encoding="utf-8")
    task = (root / "reviewer_task.txt").read_text(encoding="utf-8")
    assert "REVIEWER" in system and "Role boundary" in system and "accept" in system and "revise" in system
    for placeholder in ("${feature}", "${request}", "${objective}", "${limitations}", "${success_criteria}", "${checks}",
                        "${findings}", "${answer}", "${gaps}", "${evidence}", "${feedback}"):
        assert placeholder in task


# ---------------------------------------------------------------- shared client override

def test_llm_ask_passes_the_model_override(monkeypatch):
    seen = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": " ok "})()})()]})()

    class FakeClient:
        chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(llm, "_get_client", lambda: FakeClient())
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "default-model")
    assert llm.ask("s", "u") == "ok" and seen["model"] == "default-model"
    assert llm.ask("s", "u", model="other-model") == "ok" and seen["model"] == "other-model"
    assert llm.describe(model="other-model") == "gemini / other-model"
    assert llm.describe() == "gemini / default-model"

    class EmptyCompletions:
        def create(self, **kwargs):
            return type("R", (), {"choices": []})()

    monkeypatch.setattr(llm, "_get_client", lambda: type("C", (), {"chat": type("Chat", (), {"completions": EmptyCompletions()})()})())
    with pytest.raises(LLMUnavailable) as info:
        llm.ask("s", "u")
    assert "returned no choices" in str(info.value)


# ---------------------------------------------------------------- reads, lists, persistence, errors

def test_unknown_workflow_is_a_json_404(client):
    for path in ("/workflow/wf_deadbeef", "/workflow/wf_deadbeef/status", "/workflow/wf_deadbeef/plan",
                 "/workflow/wf_deadbeef/result", "/workflow/wf_deadbeef/review", "/workflow/wf_deadbeef/response"):
        response = client.get(path)
        assert response.status_code == 404 and "unknown workflow" in response.get_json()["error"]


def test_decision_on_unknown_workflow_is_404(client):
    response = client.post("/workflow/wf_deadbeef/decision", json={"decision": "accept"})
    assert response.status_code == 404 and "unknown workflow" in response.get_json()["error"]


def test_unknown_route_is_json_not_html(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.is_json and response.get_json()["status"] == 404


def test_list_filters_by_state_and_rejects_unknown_states(client):
    first = client.post("/workflow", json=VALID).get_json()["workflow_id"]
    second = client.post("/workflow", json={**VALID, "feature": "loans"}).get_json()["workflow_id"]
    listed = client.get("/workflows").get_json()
    assert {w["workflow_id"] for w in listed} == {first, second}
    assert {w["workflow_id"] for w in client.get("/workflows?state=awaiting_human_review").get_json()} == {first, second}
    assert client.get("/workflows?state=accepted").get_json() == []
    response = client.get("/workflows?state=bogus")
    assert response.status_code == 400 and "states" in response.get_json()


def test_workflows_survive_a_restart(tmp_path, api):
    first = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW))
    workflow_id = first.test_client().post("/workflow", json=VALID).get_json()["workflow_id"]
    assert (tmp_path / "data" / f"{workflow_id}.json").exists()

    second = make_app(tmp_path, ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW))
    reloaded = second.test_client().get(f"/workflow/{workflow_id}")
    assert reloaded.status_code == 200
    assert reloaded.get_json()["state"] == State.AWAITING_HUMAN_REVIEW
    assert reloaded.get_json()["plan"]["objective"] == GOOD_PLAN["objective"]
    assert reloaded.get_json()["result"]["answer"] == GOOD_RESULT["answer"]
    assert reloaded.get_json()["review"]["verdict"] == "accept"
    assert [s["fallback"] for s in reloaded.get_json()["stages"]] == [False, False, False, False]
    # the human decision works on the reloaded workflow: the gate survives a restart
    decided = second.test_client().post(f"/workflow/{workflow_id}/decision", json={"decision": "accept"})
    assert decided.status_code == 200 and decided.get_json()["state"] == State.ACCEPTED
    assert second.test_client().get(f"/workflow/{workflow_id}/response").status_code == 200
    assert second.test_client().get("/health").get_json()["pending"] == 0
    assert second.test_client().get("/health").get_json()["workflows"] == 1


def test_unexpected_errors_are_structured_json(app):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    app.extensions["multi_agent"]["store"].create = boom
    response = app.test_client().post("/workflow", json=VALID)
    assert response.status_code == 500
    assert response.get_json() == {"error": "RuntimeError: disk full", "status": 500}
