"""Tests for the shared Multi-Agent Server.

Everything runs against a Flask test client with temporary data and audit
directories, an inline executor (stages run before POST /workflow answers)
and a scripted model, so no server, provider or API key is needed.
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
from multi_agent_server import catalogue, config  # noqa: E402
from multi_agent_server.agents import planner  # noqa: E402
from multi_agent_server.contracts import ContractError, parse_json_object, validate_plan  # noqa: E402
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
    return ScriptedAsk(GOOD_PLAN)


@pytest.fixture
def app(tmp_path, ask):
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
    assert body["pipeline"] == ["planner"]
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

def test_valid_plan_runs_the_workflow_to_planned(client, ask, tmp_path):
    response = client.post("/workflow", json=VALID)
    assert response.status_code == 202
    body = response.get_json()
    workflow_id = body["workflow_id"]
    assert workflow_id.startswith("wf_") and len(workflow_id) == 11
    assert body["state"] == State.PLANNED and body["has_plan"] is True
    assert body["links"] == {"self": f"/workflow/{workflow_id}", "status": f"/workflow/{workflow_id}/status"}
    assert [s["role"] for s in body["stages"]] == ["planner"]
    assert body["stages"][0]["status"] == "completed" and body["stages"][0]["fallback"] is False

    # the Planner saw the request, the context and only the budgeting catalogue
    assert len(ask.calls) == 1
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
    assert plan_body["state"] == State.PLANNED
    assert plan["objective"] == GOOD_PLAN["objective"]
    assert [t["id"] for t in plan["tasks"]] == ["t1", "t2", "t3"]
    assert plan["tasks"][0]["params"] == CONTEXT
    assert plan["tasks"][2]["depends_on"] == ["t1", "t2"]
    assert plan["meta"]["source"] == "model" and plan["meta"]["attempts"] == 1
    assert plan["meta"]["accepted_first_try"] is True and plan["meta"]["model"]

    full = client.get(f"/workflow/{workflow_id}").get_json()
    assert full["plan"] == plan and full["result"] is None and full["decision"] is None
    assert full["stages"][0]["output"]["task_count"] == 3
    assert full["stages"][0]["duration_seconds"] is not None

    history, coordination = _audit(tmp_path)
    assert [r["event"] for r in history] == [
        "workflow_created", "state_changed", "stage_started", "stage_completed", "state_changed"]
    assert [(r["detail"].get("from"), r["detail"].get("to")) for r in history if r["event"] == "state_changed"] == [
        ("created", "planning"), ("planning", "planned")]
    started = next(r for r in history if r["event"] == "stage_started")
    assert started["role"] == "planner" and started["model"] and started["detail"]["timeout_seconds"] > 0
    assert [r["decision"] for r in coordination] == ["request_accepted", "plan_accepted"]
    assert coordination[1]["detail"] == {"attempts": 1, "task_count": 3, "accepted_first_try": True}
    for record in history + coordination:
        assert record["workflow_id"] == workflow_id and record["ts"].endswith("+00:00")


def test_off_contract_plan_gets_one_correction(tmp_path):
    ask = ScriptedAsk(BAD_PLAN, GOOD_PLAN)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.PLANNED
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "model" and plan["meta"]["attempts"] == 2
    assert plan["meta"]["accepted_first_try"] is False
    errors = plan["meta"]["rejections"][0]
    assert any("not in the budgeting catalogue" in e for e in errors)
    assert any("customer_id=2 does not match the context" in e for e in errors)

    assert len(ask.calls) == 2
    retry = ask.calls[1]["user"]
    assert "rejected by the handoff contract" in retry
    for error in errors:
        assert error in retry                     # the model is told exactly what to fix

    _history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination] == ["request_accepted", "plan_rejected", "plan_accepted"]
    assert coordination[1]["detail"]["attempt"] == 1 and coordination[1]["detail"]["action"] == "retry"


def test_two_off_contract_plans_fall_back_and_say_so(tmp_path):
    ask = ScriptedAsk(BAD_PLAN, "not even json")
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.PLANNED
    assert body["stages"][0] == {**body["stages"][0], "status": "completed", "fallback": True}
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback"
    assert "rejected by the contract 2 times" in plan["meta"]["fallback_reason"]
    assert len(plan["meta"]["rejections"]) == 2
    assert plan["limitations"] == ["Fallback plan built from the catalogue defaults, not from the request wording"]
    assert [t["endpoint"] for t in plan["tasks"] if t["kind"] == "api"] == ["/api/budgets/summary", "/api/transactions/spending"]
    assert plan["tasks"][-1]["kind"] == "analysis" and plan["tasks"][-1]["depends_on"] == ["t1", "t2"]

    history, coordination = _audit(tmp_path)
    assert [r["decision"] for r in coordination] == ["request_accepted", "plan_rejected", "plan_rejected", "fallback_applied"]
    assert coordination[2]["detail"]["action"] == "fallback"
    assert coordination[3]["detail"]["stage"] == "planner"
    completed = next(r for r in history if r["event"] == "stage_completed")
    assert completed["detail"]["fallback"] is True and completed["detail"]["source"] == "fallback"


def test_unavailable_model_falls_back_without_failing(tmp_path):
    ask = ScriptedAsk(LLMUnavailable("GEMINI_API_KEY is not set"))
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.PLANNED and body["stages"][0]["fallback"] is True
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback"
    assert "model unavailable: GEMINI_API_KEY is not set" in plan["meta"]["fallback_reason"]
    _history, coordination = _audit(tmp_path)
    assert coordination[-1]["decision"] == "fallback_applied"
    assert "GEMINI_API_KEY" in coordination[-1]["detail"]["reason"]


def test_slow_planner_is_timed_out_and_falls_back(tmp_path):
    def slow(system_prompt, user_prompt, **kwargs):
        time.sleep(0.5)
        return json.dumps(GOOD_PLAN)
    client = make_app(tmp_path, slow, stage_timeout=0.05).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert body["state"] == State.PLANNED
    stage = body["stages"][0]
    assert stage["status"] == "timed_out" and stage["fallback"] is True
    plan = client.get(f"/workflow/{body['workflow_id']}/plan").get_json()["plan"]
    assert plan["meta"]["source"] == "fallback" and "did not answer within 0.05s" in plan["meta"]["fallback_reason"]
    history, coordination = _audit(tmp_path)
    assert "stage_timed_out" in [r["event"] for r in history]
    assert coordination[-1]["decision"] == "fallback_applied"


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


def test_per_role_model_override_reaches_the_call(tmp_path, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_PLANNER_MODEL", "gemini-2.5-pro")
    ask = ScriptedAsk(GOOD_PLAN)
    client = make_app(tmp_path, ask).test_client()
    body = client.post("/workflow", json=VALID).get_json()
    assert ask.calls[0]["model"] == "gemini-2.5-pro"
    assert body["stages"][0]["model"].endswith("/ gemini-2.5-pro")
    assert client.get("/health").get_json()["models"]["planner"] == "gemini-2.5-pro"


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
    for path in ("/workflow/wf_deadbeef", "/workflow/wf_deadbeef/status", "/workflow/wf_deadbeef/plan"):
        response = client.get(path)
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
    assert {w["workflow_id"] for w in client.get("/workflows?state=planned").get_json()} == {first, second}
    assert client.get("/workflows?state=accepted").get_json() == []
    response = client.get("/workflows?state=bogus")
    assert response.status_code == 400 and "states" in response.get_json()


def test_workflows_survive_a_restart(tmp_path):
    first = make_app(tmp_path, ScriptedAsk(GOOD_PLAN))
    workflow_id = first.test_client().post("/workflow", json=VALID).get_json()["workflow_id"]
    assert (tmp_path / "data" / f"{workflow_id}.json").exists()

    second = make_app(tmp_path, ScriptedAsk(GOOD_PLAN))
    reloaded = second.test_client().get(f"/workflow/{workflow_id}")
    assert reloaded.status_code == 200
    assert reloaded.get_json()["state"] == State.PLANNED
    assert reloaded.get_json()["plan"]["objective"] == GOOD_PLAN["objective"]
    assert reloaded.get_json()["stages"][0]["fallback"] is False
    assert second.test_client().get("/health").get_json()["workflows"] == 1


def test_unexpected_errors_are_structured_json(app):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")
    app.extensions["multi_agent"]["store"].create = boom
    response = app.test_client().post("/workflow", json=VALID)
    assert response.status_code == 500
    assert response.get_json() == {"error": "RuntimeError: disk full", "status": 500}
