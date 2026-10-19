"""Contract checks: the budgeting routes against the real Multi-Agent Server app.

The server's Flask app runs in this process (inline executor, scripted model,
fake feature API), and the budgeting client's transport is pointed at it, so
the two sides are tested together with no network, no key and no fake server.
Run from services/budgeting/backend:

    python -m tests.test_multi_agent_contract
"""

from pathlib import Path
import json
import os
import sys
import tempfile

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parents[2]          # services/budgeting/backend -> repo root
for path in (str(BASE_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from services import multi_agent_client as ma  # noqa: E402

try:
    from multi_agent_server import evidence  # noqa: E402
    from multi_agent_server.orchestrator import InlineExecutor  # noqa: E402
    from multi_agent_server.server import create_app as create_server  # noqa: E402
    from multi_agent_server.http import FetchResult  # noqa: E402
except ImportError as exc:  # the server's requirements are not installed here
    SERVER_IMPORT_ERROR = exc
else:
    SERVER_IMPORT_ERROR = None

HX = {"HX-Request": "true"}
CONTEXT = {"customer_id": 1, "month": 9, "year": 2026}
SUMMARY_PAYLOAD = {
    "customer_id": 1, "month": 9, "year": 2026, "spending_source": "transactions-api",
    "budgets": [{"category": "Dining Out", "monthly_limit": 300.0, "spent": 325.2, "remaining": -25.2, "percent_used": 108.4,
                 "status": "OVER_BUDGET", "over_budget": True, "over_by": 25.2}],
    "totals": {"total_limit": 300.0, "total_spent": 325.2, "total_remaining": -25.2, "percent_used": 108.4, "over_budget_count": 1},
    "over_budget_categories": ["Dining Out"], "unbudgeted_spending": [],
}
BUDGET_PLAN = {"objective": "Find the over-budget categories", "success_criteria": ["Every over-budget category is named"],
               "limitations": [], "tasks": [
                   {"id": "t1", "kind": "api", "title": "Summary", "endpoint": "/api/budgets/summary", "params": CONTEXT, "evidence": "totals"},
                   {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "name them", "evidence": "x"}]}
BUDGET_RESULT = {"findings": [{"task_id": "t2", "statement": "Dining Out is over its 300.0 limit by 25.2.", "evidence": ["t1"]}],
                 "answer": "One category is over budget: Dining Out by 25.2.", "gaps": []}
LOANS_PLAN = {"objective": "List the loans", "success_criteria": ["Every loan is listed"], "limitations": [], "tasks": [
    {"id": "t1", "kind": "api", "title": "Loans", "endpoint": "/api/loans", "params": {"customer_id": 1}, "evidence": "loans"},
    {"id": "t2", "kind": "analysis", "title": "Judge", "depends_on": ["t1"], "instruction": "list", "evidence": "x"}]}
LOANS_RESULT = {"findings": [{"task_id": "t2", "statement": "You hold 1 loan of 15000.", "evidence": ["t1"]}],
                "answer": "You hold 1 loan.", "gaps": []}
REVIEW = {"verdict": "accept", "summary": "The findings match the evidence.", "criteria": [{"index": 1, "met": True, "note": "named"}],
          "defects": [], "risks": ["Internal risk the customer must not see"], "revision_notes": []}


def scripted_ask(system_prompt, user_prompt, **kwargs):
    """Answers by role and feature, so one scripted model serves both workflows."""
    loans = "Feature: loans" in user_prompt
    if "PLANNER" in system_prompt:
        return json.dumps(LOANS_PLAN if loans else BUDGET_PLAN)
    if "WORKER" in system_prompt:
        return json.dumps(LOANS_RESULT if loans else BUDGET_RESULT)
    return json.dumps(REVIEW)


def fake_fetch(base_url, path, params=None):
    payloads = {"/api/budgets/summary": SUMMARY_PAYLOAD,
                "/api/loans": [{"loan_id": 7, "loan_type": "CAR", "requested_amount": 15000, "status": "APPROVED"}]}
    return FetchResult(url=f"{base_url}{path}", status_code=200, payload=payloads.get(path, []), duration_seconds=0.01)


class Harness:
    """The real server app behind the budgeting client, plus the budgeting app itself."""

    def __init__(self, tmp):
        self.server = create_server(data_dir=Path(tmp) / "data", audit_dir=Path(tmp) / "audit",
                                    executor=InlineExecutor(), ask=scripted_ask, api_token="")
        self.server_client = self.server.test_client()
        self.server_calls = []
        from app import app
        app.config["TESTING"] = True
        self.client = app.test_client()

    def transport(self, method, path, body=None):
        self.server_calls.append((method, path))
        response = self.server_client.open(path, method=method, json=body)
        return response.status_code, response.get_json()

    def audit(self):
        audit = self.server.extensions["multi_agent"]["audit"]
        return audit.read_history(), audit.read_coordination()


def _run_contract(check):
    if SERVER_IMPORT_ERROR is not None:
        raise AssertionError(f"multi_agent_server not importable: {SERVER_IMPORT_ERROR}")
    saved_request, saved_fetch = ma._request, evidence.fetch
    saved_env = {k: os.environ.get(k) for k in ("MULTI_AGENT_ENABLED",)}
    os.environ["MULTI_AGENT_ENABLED"] = "true"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(tmp)
            ma._request = h.transport
            evidence.fetch = fake_fetch
            check(h)
    finally:
        ma._request, evidence.fetch = saved_request, saved_fetch
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _start_budgeting(h):
    r = h.client.post("/api/multi-agent/workflows", headers=HX,
                      json={"request": "Which categories went over budget in September 2026?", **CONTEXT})
    assert r.status_code == 202, r.get_json()
    return r.get_json()["workflow_id"]


def test_reject_withholds_the_answer_and_records_the_decision():
    def check(h):
        wid = _start_budgeting(h)
        full = h.client.get(f"/api/multi-agent/workflows/{wid}").get_json()
        assert full["state"] == "awaiting_human_review" and full["final_response"] is None
        assert full["result"]["answer"].startswith("One category") and full["review"]["verdict"] == "accept"
        card = h.client.get(f"/ui/multi-agent/workflows/{wid}").get_data(as_text=True)
        assert "ma-decision" in card and "One category" in card and 'hx-trigger="every 2s"' not in card   # the gate, in the card
        r = h.client.post(f"/api/multi-agent/workflows/{wid}/decision", headers=HX,
                          json={"decision": "reject", "note": "Figures are from the wrong month", "reviewer": "Khoi"})
        assert r.status_code == 200 and r.get_json()["state"] == "rejected"
        final = h.client.get(f"/api/multi-agent/workflows/{wid}").get_json()["final_response"]
        assert final["released"] is False and final["answer"] is None and final["decided_by"] == "budgeting-ui:Khoi"
        assert final["correction_note"] == "Figures are from the wrong month"
        card = h.client.get(f"/ui/multi-agent/workflows/{wid}").get_data(as_text=True)
        assert "withheld" in card and "ma-decision" not in card
        _history, coordination = h.audit()
        decided = [c for c in coordination if c["decision"] == "human_decision"]
        assert len(decided) == 1 and decided[0]["detail"]["by"] == "budgeting-ui:Khoi" and decided[0]["detail"]["decision"] == "reject"
    _run_contract(check)


def test_accept_releases_the_final_response_in_the_card():
    def check(h):
        wid = _start_budgeting(h)
        r = h.client.post(f"/ui/multi-agent/workflows/{wid}/decision", headers=HX, data={"decision": "accept", "reviewer": "Bao"})
        page = r.get_data(as_text=True)
        assert r.status_code == 200 and r.headers.get("HX-Trigger") == "ma-decided"
        assert "accepted" in page and "released" in page and BUDGET_RESULT["answer"] in page and "budgeting-ui:Bao" in page
        full = h.client.get(f"/api/multi-agent/workflows/{wid}").get_json()
        assert full["final_response"]["released"] is True and full["final_response"]["answer"] == BUDGET_RESULT["answer"]
        assert full["final_response"]["risks"] == REVIEW["risks"]            # the panel shows the review's risks with the answer
        history = h.client.get("/api/multi-agent/workflows").get_json()
        assert history["count"] == 1 and history["workflows"][0]["state"] == "accepted"
        assert history["workflows"][0]["request"].startswith("Which categories") and history["workflows"][0]["context"] == CONTEXT
    _run_contract(check)


def test_another_features_workflow_is_invisible_and_undecidable_here():
    def check(h):
        r = h.server_client.post("/workflow", json={"feature": "loans", "request": "List my loans", "context": {"customer_id": 1}})
        loans_id = r.get_json()["workflow_id"]
        assert r.get_json()["state"] == "awaiting_human_review"
        assert h.client.get(f"/api/multi-agent/workflows/{loans_id}").status_code == 404
        r = h.client.post(f"/api/multi-agent/workflows/{loans_id}/decision", headers=HX, json={"decision": "accept"})
        assert r.status_code == 404
        assert h.server_client.get(f"/workflow/{loans_id}/status").get_json()["state"] == "awaiting_human_review"
        _start_budgeting(h)
        history = h.client.get("/api/multi-agent/workflows").get_json()
        assert history["count"] == 1 and history["workflows"][0]["feature"] == "budgeting"
        assert len(h.server_client.get("/workflows").get_json()) == 2                 # the server holds both
        page = h.client.get("/ui/multi-agent/history").get_data(as_text=True)
        assert loans_id not in page and "List my loans" not in page
    _run_contract(check)


def test_bad_ids_and_cross_site_posts_never_reach_the_server():
    def check(h):
        wid = _start_budgeting(h)
        before = len(h.server_calls)
        assert h.client.get("/api/multi-agent/workflows/wf_x%3F").status_code == 400
        r = h.client.post(f"/api/multi-agent/workflows/{wid}/decision", json={"decision": "accept"})   # no HX header
        assert r.status_code == 403
        r = h.client.post(f"/ui/multi-agent/workflows/{wid}/decision", data={"decision": "accept"})     # no HX header either
        assert r.status_code == 200 and "HX-Request" in r.get_data(as_text=True)
        assert len(h.server_calls) == before                                                            # nothing was sent
        assert h.server_client.get(f"/workflow/{wid}/status").get_json()["state"] == "awaiting_human_review"
    _run_contract(check)


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
