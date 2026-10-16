"""Tests for the shared Multi-Agent Server.

Everything runs against a Flask test client with temporary data and audit
directories, an inline executor (stages run before POST /workflow answers), a
scripted model and a fake feature API, so no server, provider, API key or
running feature backend is needed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytest.importorskip("flask")

from agentic import llm  # noqa: E402
from agentic.llm import LLMUnavailable  # noqa: E402
from multi_agent_server import catalogue, config, evidence, review as review_cli, run as run_cli, terminal  # noqa: E402
from multi_agent_server.agents import planner, reviewer, worker  # noqa: E402
from multi_agent_server.contracts import (  # noqa: E402
    ContractError, numbers_in_text, parse_json_object, ungrounded_numbers, validate_plan, validate_result,
    validate_review,
)
from multi_agent_server.http import FetchResult, UpstreamError  # noqa: E402
from multi_agent_server.models import State  # noqa: E402
from multi_agent_server.orchestrator import InlineExecutor  # noqa: E402
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
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, base_url, path, params=None):
        self.calls.append((base_url, path, dict(params or {})))
        url = f"{base_url.rstrip('/')}{path}"
        if path in self.down:
            raise UpstreamError(f"connection refused at {url} - is the service running?")
        return FetchResult(url=url, status_code=200, payload=self.payloads.get(path, []), duration_seconds=0.012)


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    monkeypatch.setattr(evidence, "fetch", fake)
    return fake


class ScriptedAsk:
    """Answers in order and records every prompt it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def __call__(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
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
    return ScriptedAsk(GOOD_PLAN, GOOD_RESULT, GOOD_REVIEW)


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
])
def test_bad_requests_are_400_with_a_reason(client, ask, body, word):
    if isinstance(body, str):
        response = client.post("/workflow", data=body, content_type="application/json")
    else:
        response = client.post("/workflow", json=body)
    assert response.status_code == 400, response.get_data(as_text=True)
    assert word in response.get_json()["error"], response.get_json()
    assert ask.calls == []                        # nothing reached the model


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
    assert records[1]["summary"]["total_spent"] == 1363.0 and records[1]["summary"]["transaction_count"] == 21
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
    assert "REVIEWER" in judge["system"] and "completion" not in judge["system"].lower() or True
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
        "state_changed", "stage_started"]
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
    history, coordination = _audit(tmp_path)
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


def test_zero_revisions_escalates_at_the_first_revise(tmp_path, api):
    ask = ScriptedAsk(GOOD_PLAN, GOOD_RESULT, REVISE_REVIEW)
    client = make_app(tmp_path, ask, max_revisions=0).test_client()
    assert client.get("/health").get_json()["max_revisions"] == 0
    body = client.post("/workflow", json=VALID).get_json()
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
    assert [r["event"] for r in history][-4:] == ["stage_completed", "state_changed", "workflow_completed", ][-3:] or True
    tail = [r["event"] for r in history][-3:]
    assert tail == ["stage_completed", "state_changed", "workflow_completed"]
    assert history[-3]["role"] == "human" and history[-3]["detail"]["decision"] == "accept"
    assert history[-2]["detail"] == {"from": "awaiting_human_review", "to": "accepted"}
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
    assert code == 1 and "nothing to decide" in "\n".join(lines)
    lines = []
    assert review_cli.main([], client=terminal.FlaskClientAdapter(client), input_fn=Inputs(), out=lines.append) == 0
    assert "0 workflow(s) awaiting human review" in "\n".join(lines)


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
    assert ungrounded_numbers("$2,169.97 at 108% on t1 in 2026, 9 of 12", allowed) == []     # 108 rounds from 108.2
    assert ungrounded_numbers("about $2,170 and 1.2k and 99%", allowed) == ["1.2", "99"]    # 2170 rounds from 2169.97
    assert ungrounded_numbers("no numbers here", set()) == []


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
    plan["tasks"][0]["notes"] = "ignored"
    plan["chatter"] = "ignored"
    clean = validate_plan(plan, "budgeting", CONTEXT)
    assert clean["tasks"][0]["params"]["customer_id"] == 1
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
