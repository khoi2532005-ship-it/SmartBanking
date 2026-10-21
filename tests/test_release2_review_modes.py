"""Tests for the Release 2 review modes: multi_agent_review, testing_review, cloud_deployment_review.

The evidence files are written into a temporary folder and the LLM is
scripted, so no server, no API key and no network are needed. The cases that
matter are the ADAPT ones: an entry that invents a workflow id, drops a stage,
misquotes a decision, a scan count, an outcome or an AI service's state is
rejected with a reason the model can act on, and the corrected retry passes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentic import llm, loop, modes, prompts  # noqa: E402
from agentic.modes.cloud_deployment_review import CloudDeploymentReviewMode  # noqa: E402
from agentic.modes.multi_agent_review import MultiAgentReviewMode  # noqa: E402
from agentic.modes.testing_review import TestingReviewMode  # noqa: E402

# ---------------------------------------------------------------- scripted model

@pytest.fixture
def answers(monkeypatch):
    scripted: list[str] = []

    def fake_ask(system_prompt, user_prompt, **kwargs):
        if kwargs.get("review"):
            return "Risk: none.\nCorrection: none.\nRetest: repeat."
        assert scripted, "llm.ask called more times than the script allows"
        return scripted.pop(0)

    monkeypatch.setattr(llm, "ask", fake_ask)
    monkeypatch.setattr(llm, "describe", lambda **kw: "stub/stub")
    return scripted


# ---------------------------------------------------------------- multi-agent audit records

WF_A, WF_B = "wf_0a1b2c3d", "wf_4e5f6a7b"
MODEL = "gemini / gemini-flash-lite-latest"


def _workflow_records(wid: str, feature: str, decision: str, by: str, t0: int):
    """History and coordination lines for one workflow that ran planner -> worker -> reviewer -> human."""
    ts = lambda s: f"2026-10-20T10:{t0 + s:02d}:00+00:00"  # noqa: E731
    h = [
        {"ts": ts(0), "workflow_id": wid, "feature": feature, "state": "created", "event": "workflow_created", "role": "", "model": "",
         "detail": {"request": "Which budget categories went over the limit?", "context": {"customer_id": 1, "month": 9, "year": 2026}}},
        {"ts": ts(0), "workflow_id": wid, "feature": feature, "state": "planning", "event": "state_changed", "role": "", "model": "", "detail": {"from": "created", "to": "planning"}},
        {"ts": ts(0), "workflow_id": wid, "feature": feature, "state": "planning", "event": "stage_started", "role": "planner", "model": MODEL, "detail": {"attempt": 1}},
        {"ts": ts(1), "workflow_id": wid, "feature": feature, "state": "planning", "event": "stage_completed", "role": "planner", "model": MODEL, "detail": {"attempt": 1, "duration_seconds": 2.0, "fallback": False, "error": ""}},
        {"ts": ts(1), "workflow_id": wid, "feature": feature, "state": "working", "event": "state_changed", "role": "", "model": "", "detail": {"from": "planned", "to": "working"}},
        {"ts": ts(1), "workflow_id": wid, "feature": feature, "state": "working", "event": "stage_started", "role": "worker", "model": MODEL, "detail": {"attempt": 1}},
        {"ts": ts(2), "workflow_id": wid, "feature": feature, "state": "working", "event": "stage_completed", "role": "worker", "model": MODEL, "detail": {"attempt": 1, "duration_seconds": 1.5, "fallback": False, "error": ""}},
        {"ts": ts(2), "workflow_id": wid, "feature": feature, "state": "reviewing", "event": "stage_started", "role": "reviewer", "model": MODEL, "detail": {"attempt": 1}},
        {"ts": ts(3), "workflow_id": wid, "feature": feature, "state": "reviewing", "event": "stage_completed", "role": "reviewer", "model": MODEL, "detail": {"attempt": 1, "duration_seconds": 1.8, "fallback": False, "error": ""}},
        {"ts": ts(3), "workflow_id": wid, "feature": feature, "state": "awaiting_human_review", "event": "state_changed", "role": "", "model": "", "detail": {"from": "reviewed", "to": "awaiting_human_review"}},
        {"ts": ts(3), "workflow_id": wid, "feature": feature, "state": "awaiting_human_review", "event": "stage_started", "role": "human", "model": "human", "detail": {"attempt": 1}},
        {"ts": ts(5), "workflow_id": wid, "feature": feature, "state": "awaiting_human_review", "event": "stage_completed", "role": "human", "model": "human", "detail": {"attempt": 1, "duration_seconds": 120.0, "fallback": False, "error": ""}},
        {"ts": ts(5), "workflow_id": wid, "feature": feature, "state": "accepted" if decision == "accept" else "rejected", "event": "state_changed", "role": "", "model": "",
         "detail": {"from": "awaiting_human_review", "to": "accepted" if decision == "accept" else "rejected"}},
        {"ts": ts(5), "workflow_id": wid, "feature": feature, "state": "accepted" if decision == "accept" else "rejected", "event": "workflow_completed", "role": "", "model": "", "detail": {}},
    ]
    c = [
        {"ts": ts(0), "workflow_id": wid, "state": "created", "decision": "request_accepted", "actor": "orchestrator", "detail": {"feature": feature}},
        {"ts": ts(1), "workflow_id": wid, "state": "planning", "decision": "plan_accepted", "actor": "orchestrator", "detail": {"attempts": 1, "task_count": 2, "accepted_first_try": True}},
        {"ts": ts(1), "workflow_id": wid, "state": "working", "decision": "handoff", "actor": "orchestrator", "detail": {"from": "planner", "to": "worker", "contract": "plan"}},
        {"ts": ts(2), "workflow_id": wid, "state": "working", "decision": "result_accepted", "actor": "orchestrator", "detail": {"attempt": 1, "accepted_first_try": True}},
        {"ts": ts(2), "workflow_id": wid, "state": "reviewing", "decision": "handoff", "actor": "orchestrator", "detail": {"from": "worker", "to": "reviewer", "contract": "result"}},
        {"ts": ts(3), "workflow_id": wid, "state": "reviewing", "decision": "verdict_recorded", "actor": "reviewer", "detail": {"verdict": "accept", "defects": 0}},
        {"ts": ts(3), "workflow_id": wid, "state": "reviewing", "decision": "review_accepted", "actor": "orchestrator", "detail": {"attempt": 1}},
        {"ts": ts(3), "workflow_id": wid, "state": "awaiting_human_review", "decision": "handoff", "actor": "orchestrator", "detail": {"from": "reviewer", "to": "human", "contract": "review"}},
        {"ts": ts(3), "workflow_id": wid, "state": "awaiting_human_review", "decision": "awaiting_decision", "actor": "orchestrator", "detail": {}},
        {"ts": ts(5), "workflow_id": wid, "state": "awaiting_human_review", "decision": "human_decision", "actor": "human", "detail": {"decision": decision, "by": by, "note": ""}},
        {"ts": ts(5), "workflow_id": wid, "state": "accepted" if decision == "accept" else "rejected",
         "decision": "response_released" if decision == "accept" else "response_withheld", "actor": "orchestrator", "detail": {}},
    ]
    return h, c


@pytest.fixture
def audit(tmp_path, monkeypatch):
    folder = tmp_path / "audit"
    folder.mkdir()
    ha, ca = _workflow_records(WF_A, "budgeting", "accept", "budgeting-ui:Bao", 0)
    hb, cb = _workflow_records(WF_B, "budgeting", "reject", "terminal:Bao", 10)
    (folder / "workflow_history.jsonl").write_text("\n".join(json.dumps(r) for r in ha + hb) + "\n", encoding="utf-8")
    (folder / "coordination_audit.jsonl").write_text("\n".join(json.dumps(r) for r in ca + cb) + "\n", encoding="utf-8")
    monkeypatch.setenv("MULTI_AGENT_AUDIT_DIR", str(folder))
    return folder


GOOD_MA = (
    f"Workflows: 2 reviewed - {WF_A}, {WF_B}\n"
    "Stages: planner 2/2, worker 2/2, reviewer 2/2, human 2/2; fallbacks 0; revisions 0\n"
    f"Decisions: accept 1, partially_accept 0, reject 1; {WF_A} accept, {WF_B} reject\n"
    "Metrics: plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.50\n"
    "Recommendation: Keep the one-revision budget and the human gate as they are; both workflows passed the reviewer first try and the rejection was recorded with the response withheld.\n"
    "Verdict: PASS - every stage completed, no fallback, no handoff anomaly and both decisions are recorded."
)


# ---------------------------------------------------------------- registry and prompts

def test_three_review_modes_are_on_the_menu():
    for key in ("multi_agent_review", "testing_review", "cloud_deployment_review"):
        assert key in modes.MODES, key
        assert modes.MODES[key].label and modes.MODES[key].owner == "Bao"
    assert list(modes.MODES)[-3:] == ["multi_agent_review", "testing_review", "cloud_deployment_review"]


def test_prompt_files_exist_and_are_not_inline():
    for family in ("_multi_agent_review", "_testing_review", "_cloud_review"):
        assert len(prompts.load_all(family, "review_system.txt", "review_task.txt")) == 2


# ---------------------------------------------------------------- multi_agent_review

def test_multi_agent_faithful_entry_passes_first_time(answers, audit):
    answers.append(GOOD_MA)
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and not result.adapted
    f = result.evidence.facts
    assert f["ids"] == [WF_A, WF_B] and f["decisions"] == {"accept": 1, "reject": 1}
    assert f["stage_totals"]["human"] == {"started": 2, "completed": 2}
    assert f["rates"]["human_acceptance_rate"] == 0.5 and not result.evidence.degraded
    assert f["source_kind"] == "MULTI_AGENT_AUDIT_DIR"


def test_multi_agent_invented_workflow_id_is_rejected_then_corrected(answers, audit):
    answers.extend([GOOD_MA.replace(f"{WF_A}, {WF_B}", f"{WF_A}, {WF_B}, wf_deadbeef"), GOOD_MA])
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and result.adapted
    assert "wf_deadbeef" in result.attempts[0].verdict.feedback
    assert "wf_deadbeef" in result.attempts[1].adapt_note


def test_multi_agent_dropped_stage_is_rejected(answers, audit):
    answers.extend([GOOD_MA.replace("reviewer 2/2, ", ""), GOOD_MA])
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and result.adapted
    assert "dropped reviewer" in result.attempts[0].verdict.feedback


def test_multi_agent_misquoted_decision_is_rejected(answers, audit):
    answers.extend([GOOD_MA.replace(f"{WF_B} reject", f"{WF_B} accept"), GOOD_MA])
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and result.adapted
    assert f"misquotes {WF_B}" in result.attempts[0].verdict.feedback and "reject" in result.attempts[0].verdict.feedback


def test_multi_agent_misquoted_metric_is_rejected(answers, audit):
    answers.extend([GOOD_MA.replace("human acceptance 0.50", "human acceptance 1.00"), GOOD_MA])
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and result.adapted
    assert "human acceptance 0.50" in result.attempts[0].verdict.feedback


def test_multi_agent_fallback_stage_is_degraded_and_needs_attention(answers, audit):
    history = (audit / "workflow_history.jsonl").read_text(encoding="utf-8")
    history = history.replace('"role": "worker", "model": "gemini / gemini-flash-lite-latest", "detail": {"attempt": 1, "duration_seconds": 1.5, "fallback": false',
                              '"role": "worker", "model": "gemini / gemini-flash-lite-latest", "detail": {"attempt": 1, "duration_seconds": 1.5, "fallback": true', 1)
    (audit / "workflow_history.jsonl").write_text(history, encoding="utf-8")
    soft = GOOD_MA.replace("fallbacks 0", "fallbacks 1")
    honest = soft.replace("Verdict: PASS", "Verdict: ATTENTION")
    answers.extend([soft, honest])
    result = loop.run(MultiAgentReviewMode())
    assert result.ok and result.adapted and result.evidence.degraded
    assert "ATTENTION" in result.attempts[0].verdict.feedback
    assert "fallback" in result.evidence.note


def test_multi_agent_no_audit_files_never_calls_the_model(answers, tmp_path, monkeypatch):
    monkeypatch.setenv("MULTI_AGENT_AUDIT_DIR", str(tmp_path / "empty"))
    monkeypatch.setattr("agentic.modes.multi_agent_review.REPO_ROOT", tmp_path)
    monkeypatch.setattr("agentic.modes.multi_agent_review.DOCS_DIR", tmp_path / "docs")
    result = loop.run(MultiAgentReviewMode())
    assert not result.ok and result.attempts == []
    assert "multi_agent_server.server" in result.evidence.summary


# ---------------------------------------------------------------- testing_review

PRE_4 = {"student": "student-4", "feature": "budgeting", "commit": "524bac2",
         "scans": [{"name": "ruff-security", "result": "passed", "findings": 4, "fixed": 0, "accepted": [{"id": "S104"}] * 4},
                   {"name": "detect-secrets", "result": "passed", "findings": 0, "fixed": 0, "accepted": []},
                   {"name": "pip-audit", "result": "passed", "findings": 7, "fixed": 7, "accepted": []}],
         "summary": {"result": "passed"}}
POST_4 = {"student": "student-4", "commit": "32546bf", "run_id": "39444432605",
          "tests": [{"test": "t1", "method": "GET", "endpoint": "/api/budgets/summary", "outcome": "passed"},
                    {"test": "t2", "method": "POST", "endpoint": "/api/budgets", "outcome": "passed"}],
          "summary": {"endpoints": 2, "passed": 2, "failed": 0, "checks": 27, "result": "passed"}}
JUNIT_3 = ('<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="14" failures="0" errors="0" skipped="0">'
           '<testcase name="t"/></testsuite></testsuites>')

GOOD_TR = (
    "Pre-commit: student-1 none; student-2 none; student-3 none; student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; student-5 none\n"
    "Post-commit: student-1 none; student-2 none; student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 27 checks); student-5 none\n"
    "Coverage: 1 of 5 students have a pre-commit report, 2 of 5 have a post-commit report; missing: student-1, student-2, student-3, student-5\n"
    "Recommendation: Students 1, 2 and 5 should commit both reports and student 3 the pre-commit report before the Testing Review can pass.\n"
    "Verdict: ATTENTION - four students are missing a report, although every report present passed."
)


@pytest.fixture
def reports(tmp_path, monkeypatch):
    docs = tmp_path / "testing"
    docs.mkdir()
    (docs / "pre-commit-security-report-student-4.json").write_text(json.dumps(PRE_4), encoding="utf-8")
    (docs / "post-commit-endpoint-report-student-4.json").write_text(json.dumps(POST_4), encoding="utf-8")
    ci = tmp_path / "ci" / "student-3"
    ci.mkdir(parents=True)
    (ci / "student-3-endpoint-tests.xml").write_text(JUNIT_3, encoding="utf-8")
    monkeypatch.setenv("TESTING_REPORTS_DIR", str(docs))
    monkeypatch.setenv("CI_EVIDENCE_DIR", str(tmp_path / "ci"))
    return docs


def test_testing_faithful_entry_passes_first_time(answers, reports):
    answers.append(GOOD_TR)
    result = loop.run(TestingReviewMode())
    assert result.ok and not result.adapted
    f = result.evidence.facts
    assert f["with_pre_commit"] == ["student-4"] and f["with_post_commit"] == ["student-3", "student-4"]
    assert f["missing"] == ["student-1", "student-2", "student-3", "student-5"] and f["attention"]
    assert not result.evidence.degraded


def test_testing_misquoted_scan_count_is_rejected_then_corrected(answers, reports):
    answers.extend([GOOD_TR.replace("pip-audit 7/7/0 passed", "pip-audit 7/0/0 passed"), GOOD_TR])
    result = loop.run(TestingReviewMode())
    assert result.ok and result.adapted
    assert "misquotes student-4 pip-audit" in result.attempts[0].verdict.feedback


def test_testing_invented_scan_is_rejected(answers, reports):
    answers.extend([GOOD_TR.replace("pip-audit 7/7/0 passed", "pip-audit 7/7/0 passed, bandit 0/0/0 passed"), GOOD_TR])
    result = loop.run(TestingReviewMode())
    assert result.ok and result.adapted
    assert "bandit" in result.attempts[0].verdict.feedback


def test_testing_wrong_outcome_and_coverage_are_rejected(answers, reports):
    wrong = GOOD_TR.replace("POST /api/budgets passed", "POST /api/budgets failed").replace("2 of 5 have a post-commit", "1 of 5 have a post-commit")
    answers.extend([wrong, GOOD_TR])
    result = loop.run(TestingReviewMode())
    assert result.ok and result.adapted
    feedback = result.attempts[0].verdict.feedback
    assert "misquotes student-4 POST /api/budgets" in feedback and "2 of 5 students for post-commit" in feedback


def test_testing_pass_claimed_with_missing_reports_is_rejected(answers, reports):
    answers.extend([GOOD_TR.replace("Verdict: ATTENTION", "Verdict: PASS"), GOOD_TR])
    result = loop.run(TestingReviewMode())
    assert result.ok and result.adapted
    assert "must start with ATTENTION" in result.attempts[0].verdict.feedback


def test_testing_no_reports_never_calls_the_model(answers, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING_REPORTS_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("CI_EVIDENCE_DIR", str(tmp_path / "none-ci"))
    result = loop.run(TestingReviewMode())
    assert not result.ok and result.attempts == []
    assert "pre-commit-security-report-student-<N>.json" in result.evidence.summary


def test_testing_unreadable_report_counts_as_missing_and_degrades(answers, reports):
    (reports / "pre-commit-security-report-student-2.json").write_text("{not json", encoding="utf-8")
    answers.append(GOOD_TR)
    result = loop.run(TestingReviewMode())
    assert result.ok and result.evidence.degraded
    assert "student-2" in result.evidence.note and "student-2" in result.evidence.facts["missing"]


# ---------------------------------------------------------------- cloud_deployment_review

REPORT = {
    "provider": "azure", "region": "australiaeast", "environment": "release-2-baseline", "commit": "9ab12cd",
    "deployed_at": "2026-10-24T01:00:00Z", "deployed_by": "David Lee",
    "workflow": {"name": "cloud-deployment.yml", "run_id": "41000000001", "run_url": "https://example/runs/41000000001", "conclusion": "success"},
    "scripts": ["deploy/azure/deploy.sh"],
    "resources": [{"name": "smartbank-vm", "type": "virtual-machine", "status": "running"},
                  {"name": "smartbank-ip", "type": "public-ip", "status": "assigned"}],
    "endpoints": [{"name": "home page", "method": "GET", "url": "http://20.1.2.3:3000/", "expected_status": 200, "status": 200},
                  {"name": "budgeting api health", "method": "GET", "url": "http://20.1.2.3:5004/api/health", "expected_status": 200, "status": 200}],
    "crud_checks": [{"name": "budget create", "method": "POST", "url": "http://20.1.2.3:5004/api/budgets", "expected_status": 201, "status": 201},
                    {"name": "budget delete", "method": "DELETE", "url": "http://20.1.2.3:5004/api/budgets/15", "expected_status": 200, "status": 200}],
    "ai_services": {"ai_mode": "disabled", "mcp": "disabled", "rag": "disabled", "multi_agent": "disabled"},
    "issues": [],
    "release_decision": {"decision": "", "by": "", "note": "", "decided_at": ""},
}

GOOD_CD = (
    "Deployment: azure australiaeast, commit 9ab12cd, workflow run 41000000001 success, 2 resources\n"
    "Endpoints: 2/2 checks passed - home page 200, budgeting api health 200\n"
    "AI services: ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled\n"
    "CRUD: 2/2 checks passed - budget create 201, budget delete 200\n"
    "Release recommendation: approve - every endpoint and CRUD check returned its expected status, the run succeeded and no issue is open.\n"
    "Human decision: pending\n"
    "Verdict: PASS - the baseline deployment answers on every checked endpoint with the AI services disabled."
)


@pytest.fixture
def cloud_report(tmp_path, monkeypatch):
    path = tmp_path / "cloud-deployment-report.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    monkeypatch.setenv("CLOUD_DEPLOYMENT_REPORT", str(path))
    return path


def test_cloud_faithful_entry_passes_first_time(answers, cloud_report):
    answers.append(GOOD_CD)
    result = loop.run(CloudDeploymentReviewMode())
    assert result.ok and not result.adapted and not result.evidence.degraded
    f = result.evidence.facts
    assert f["recommendation"] == "approve" and f["human_decision"] == "pending" and not f["attention"]


def test_cloud_enabled_ai_service_claim_is_rejected(answers, cloud_report):
    answers.extend([GOOD_CD.replace("mcp disabled", "mcp enabled"), GOOD_CD])
    result = loop.run(CloudDeploymentReviewMode())
    assert result.ok and result.adapted
    assert "misquotes mcp" in result.attempts[0].verdict.feedback


def test_cloud_failed_check_forces_hold_and_attention(answers, cloud_report):
    report = json.loads(cloud_report.read_text(encoding="utf-8"))
    report["crud_checks"][0]["status"] = 500
    cloud_report.write_text(json.dumps(report), encoding="utf-8")
    honest = (GOOD_CD.replace("CRUD: 2/2 checks passed - budget create 201", "CRUD: 1/2 checks passed - budget create 500")
              .replace("Release recommendation: approve - every endpoint and CRUD check returned its expected status, the run succeeded and no issue is open.",
                       "Release recommendation: hold - budget create returned 500 instead of 201.")
              .replace("Verdict: PASS", "Verdict: ATTENTION"))
    answers.extend([GOOD_CD, honest])
    result = loop.run(CloudDeploymentReviewMode())
    assert result.ok and result.adapted and result.evidence.facts["recommendation"] == "hold"
    feedback = result.attempts[0].verdict.feedback
    assert "must read hold" in feedback and "1/2 checks" in feedback


def test_cloud_human_decision_is_recorded_and_must_be_quoted(answers, cloud_report):
    report = json.loads(cloud_report.read_text(encoding="utf-8"))
    report["release_decision"] = {"decision": "approved", "by": "Khoi", "note": "baseline only", "decided_at": "2026-10-24T02:00:00Z"}
    cloud_report.write_text(json.dumps(report), encoding="utf-8")
    decided = GOOD_CD.replace("Human decision: pending", "Human decision: approved by Khoi")
    answers.extend([GOOD_CD, decided])
    result = loop.run(CloudDeploymentReviewMode())
    assert result.ok and result.adapted
    assert "approved" in result.attempts[0].verdict.feedback and result.evidence.facts["decided_by"] == "Khoi"


def test_cloud_sample_report_is_reviewed_as_degraded(answers, monkeypatch):
    monkeypatch.delenv("CLOUD_DEPLOYMENT_REPORT", raising=False)
    monkeypatch.setattr("agentic.modes.cloud_deployment_review.DEFAULT_REPORT", Path("/nonexistent/cloud-deployment-report.json"))
    mode = CloudDeploymentReviewMode()
    evidence = mode.collect()
    assert evidence.ok and evidence.degraded and evidence.facts["is_sample"]
    assert "sample" in evidence.note and evidence.facts["provider"] == "azure"
    # the entry must admit it reviewed the sample
    answers.extend([
        "Deployment: azure australiaeast, commit 0000000, workflow run 0 success, 3 resources\n"
        "Endpoints: 3/3 checks passed - home page 200, budgeting api health 200, budgets list 200\n"
        "AI services: ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled\n"
        "CRUD: 3/3 checks passed - budget create 201, budget read 200, budget delete 200\n"
        "Release recommendation: approve - every check returned its expected status and no issue is open.\n"
        "Human decision: pending\n"
        "Verdict: PASS - every check passed.",
        "Deployment: azure australiaeast, commit 0000000, workflow run 0 success, 3 resources\n"
        "Endpoints: 3/3 checks passed - home page 200, budgeting api health 200, budgets list 200\n"
        "AI services: ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled\n"
        "CRUD: 3/3 checks passed - budget create 201, budget read 200, budget delete 200\n"
        "Release recommendation: approve - every check returned its expected status and no issue is open.\n"
        "Human decision: pending\n"
        "Verdict: PASS - this is the sample report, not a real deployment; every sample check passed.",
    ])
    result = loop.run(mode)
    assert result.ok and result.adapted and result.evidence.degraded
    assert "sample" in result.attempts[0].verdict.feedback


def test_cloud_missing_configured_report_never_calls_the_model(answers, tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_DEPLOYMENT_REPORT", str(tmp_path / "missing.json"))
    result = loop.run(CloudDeploymentReviewMode())
    assert not result.ok and result.attempts == []
    assert "docs/deployment/cloud-deployment-report-format.md" in result.evidence.summary
