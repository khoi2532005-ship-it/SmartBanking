"""deploy/azure/checks.py's report: the AI services must be what the deployment
asked for. The baseline keeps all four off; the bonus profile turns on the ones
whose switch was set (AI_MODE_ENABLED, MCP_ENABLED, MULTI_AGENT_ENABLED), and
each server that is on must also answer a real call through the application."""

import pytest

from deploy.azure import checks

ALL_OFF = dict.fromkeys(checks.AI_SERVICES, "disabled")
META = {"region": "r", "deployed_at": "t", "commit": "c", "deployed_by": "u", "workflow": {}}


@pytest.fixture
def report(monkeypatch):
    """build_report with no HTTP: every call answers as expected, the given AI states."""
    def answered(results, name, method, url, expected_status, **kwargs):
        results.append({"name": name, "method": method, "url": url, "expected_status": expected_status,
                        "status": expected_status})
    monkeypatch.setattr(checks, "_check", answered)
    monkeypatch.setattr(checks, "endpoint_checks", lambda feature, url: [])
    monkeypatch.setattr(checks, "crud_checks", lambda feature, url: [])

    def build(states, **requested):
        monkeypatch.setattr(checks, "ai_services", lambda url: states)
        urls = dict.fromkeys(checks.FEATURES, "https://x")
        return checks.build_report(urls, "https://home", {**META, "requested": requested})
    return build


def test_the_baseline_wants_all_four_off(report):
    r = report(ALL_OFF)
    assert (r["profile"], r["issues"]) == ("baseline", [])
    assert report({**ALL_OFF, "ai_mode": "enabled"})["issues"] == [
        "ai_mode is enabled, expected disabled (baseline profile)"]


def test_the_bonus_profile_wants_what_was_switched_on(report):
    r = report({**ALL_OFF, "ai_mode": "enabled"}, ai_mode=True)
    assert (r["profile"], r["issues"]) == ("bonus", [])
    assert report(ALL_OFF, ai_mode=True)["issues"] == ["ai_mode is disabled, expected enabled (bonus profile)"]
    assert report({**ALL_OFF, "ai_mode": "enabled", "mcp": "enabled"}, ai_mode=True)["issues"] == [
        "mcp is enabled, expected disabled (bonus profile)"]
    on = {**ALL_OFF, "ai_mode": "enabled", "mcp": "enabled", "multi_agent": "enabled"}
    assert report(on, ai_mode=True, mcp=True, multi_agent=True)["issues"] == []


class Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


GROUNDED = Reply(200, {"answer": "An alert is new, reviewed, dismissed or confirmed [fraud-alerts-feature:3].",
                       "citations": [{"chunk_id": "fraud-alerts-feature:3"}], "confidence_category": "high",
                       "insufficient_context": False, "retrieval_summary": {}})
INSUFFICIENT = Reply(200, {"answer": "Insufficient context.", "citations": [], "confidence_category": "low",
                           "insufficient_context": True, "retrieval_summary": {}})
STARTED = Reply(202, {"workflow_id": "wf_0a1b2c3d", "state": "planning"})
RELEASED = Reply(200, {"workflow_id": "wf_0a1b2c3d", "state": "accepted",
                       "final_response": {"released": True, "decision": "accept", "answer": "7 alerts, 2 new."}})


@pytest.fixture
def interactions(monkeypatch):
    """checks.ai_interactions with no HTTP and no waiting: each (method, path) answers
    with the given Reply, or with the next of a list of Replies on each call."""
    monkeypatch.setattr(checks.time, "sleep", lambda seconds: None)

    def run(replies, **requested):
        calls = []

        def fake_check(results, name, method, url, expected_status, **kwargs):
            path = url.replace("https://x", "")
            reply = replies.get((method, path))
            if isinstance(reply, list):
                reply = reply.pop(0) if len(reply) > 1 else reply[0]
            calls.append((method, path, kwargs.get("json")))
            results.append({"name": name, "method": method, "url": url, "expected_status": expected_status,
                            "status": reply.status_code if reply else None})
            return reply
        monkeypatch.setattr(checks, "_check", fake_check)
        records, issues = checks.ai_interactions("https://x", requested)
        return records, issues, calls
    return run


def test_the_baseline_makes_no_ai_call(interactions):
    assert interactions({}) == ([], [], [])


def test_mcp_on_means_a_real_tool_call_through_the_application(interactions):
    # Bonus B2 asks for "a successful MCP tool interaction through the
    # application": fraud's own tool, called by its backend, not just tools/list.
    tools = Reply(200, {"tool_count": 5, "tools": [{"name": "fraud_alerts_count"}]})
    called = Reply(200, {"tool": "fraud_alerts_count", "arguments": {}, "result": {"count": 7}})
    records, issues, calls = interactions({("GET", "/api/mcp/tools"): tools, ("POST", "/api/mcp/tool"): called}, mcp=True)
    assert [c[:2] for c in calls] == [("GET", "/api/mcp/tools"), ("POST", "/api/mcp/tool")]
    assert [(r["name"], r["status"], r["ok"]) for r in records] == [("fraud mcp tools", 200, True),
                                                                     ("fraud mcp tool call", 200, True)]
    assert issues == [] and "count" in records[1]["detail"]
    # A 200 whose body carries no tool result is not an interaction.
    records, issues, _ = interactions({("GET", "/api/mcp/tools"): tools, ("POST", "/api/mcp/tool"): Reply(200, {"error": "x"})}, mcp=True)
    assert records[1]["ok"] is False and issues == ["fraud mcp tool call: the reply carries no tool result"]


def test_rag_on_means_a_grounded_answer_with_citations(interactions):
    # Bonus B3 asks for "a successful grounded response using retrieved context".
    records, issues, calls = interactions({("POST", "/api/rag/query"): GROUNDED}, rag=True)
    assert calls == [("POST", "/api/rag/query", {"query": checks.RAG_QUESTION})]
    assert records[0]["name"] == "fraud rag query" and records[0]["ok"] is True and issues == []
    assert "1 citation" in records[0]["detail"] and "high" in records[0]["detail"]
    # "Insufficient context" is a valid 200 from the server, but it is not a grounded answer.
    records, issues, _ = interactions({("POST", "/api/rag/query"): INSUFFICIENT}, rag=True)
    assert records[0]["ok"] is False
    assert issues == ["fraud rag query: the RAG server found no relevant document (insufficient context), so nothing was grounded"]
    # A server that is unreachable through the backend (503) is the same failure as any check.
    records, issues, _ = interactions({("POST", "/api/rag/query"): Reply(503, {"error": "down", "unreachable": True})}, rag=True)
    assert (records[0]["status"], records[0]["ok"]) == (503, False) and issues == []   # build_report reports the status mismatch


def test_multi_agent_on_means_a_workflow_is_decided_and_released(interactions):
    # Bonus B4 asks for "a successful Planner -> Worker -> Reviewer workflow":
    # started through fraud, followed to the human gate, decided, released.
    gate = Reply(200, {"workflow_id": "wf_0a1b2c3d", "state": "awaiting_human_review", "final_response": None})
    waiting = [Reply(200, {"workflow_id": "wf_0a1b2c3d", "state": "working", "final_response": None}),
               gate, gate,   # the poll that sees the gate, then the look that goes into the report
               RELEASED]     # read back after the decision
    replies = {("POST", "/api/agents/workflow"): STARTED, ("GET", "/api/agents/workflow/wf_0a1b2c3d"): waiting,
               ("POST", "/api/agents/workflow/wf_0a1b2c3d/review"): Reply(200, {"state": "accepted", "released": True})}
    records, issues, calls = interactions(replies, multi_agent=True)
    assert [(c[0], c[1]) for c in calls][:2] == [("POST", "/api/agents/workflow"), ("GET", "/api/agents/workflow/wf_0a1b2c3d")]
    assert calls[0][2] == {"task": checks.WORKFLOW_TASK, "customer_id": 1}
    review = next(c for c in calls if c[1].endswith("/review"))
    assert review[2]["decision"] == "accept" and review[2]["reviewer"], "fraud records who decided"
    assert [(r["name"], r["status"], r["ok"]) for r in records] == [
        ("fraud multi-agent start", 202, True), ("fraud multi-agent gate", 200, True),
        ("fraud multi-agent decision", 200, True), ("fraud multi-agent release", 200, True)]
    assert issues == [] and "released" in records[3]["detail"]


def test_a_workflow_that_fails_or_is_withheld_is_an_issue(interactions):
    failed = Reply(200, {"workflow_id": "wf_0a1b2c3d", "state": "failed", "final_response": None, "error": "planner timed out"})
    records, issues, calls = interactions({("POST", "/api/agents/workflow"): STARTED,
                                           ("GET", "/api/agents/workflow/wf_0a1b2c3d"): failed}, multi_agent=True)
    assert not any(c[1].endswith("/review") for c in calls), "nothing is decided when the workflow never reached the gate"
    assert records[1]["ok"] is False and issues == ["fraud multi-agent gate: the workflow ended in state failed (planner timed out)"]
    # A start that the backend refuses stops there.
    records, issues, calls = interactions({("POST", "/api/agents/workflow"): Reply(503, {"error": "off", "disabled": True})},
                                          multi_agent=True)
    assert len(calls) == 1 and records[0]["status"] == 503 and issues == []


def test_build_report_folds_the_interactions_into_endpoints_and_issues(report, monkeypatch):
    monkeypatch.setattr(checks, "ai_interactions", lambda url, requested: (
        [{"name": "fraud rag query", "method": "POST", "url": f"{url}/api/rag/query", "expected_status": 200,
          "status": 200, "ok": False, "detail": "insufficient context"}], ["fraud rag query: not grounded"]))
    r = report({**ALL_OFF, "rag": "enabled"}, rag=True)
    assert [e["name"] for e in r["endpoints"]] == ["home page", "fraud rag query"]
    assert r["issues"] == ["fraud rag query: not grounded"]


def test_the_run_says_which_services_were_asked_for(monkeypatch):
    for name in ("AI_MODE_ENABLED", "MCP_ENABLED", "RAG_ENABLED", "MULTI_AGENT_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "TRUE")
    assert checks._run_meta()["requested"] == {"ai_mode": False, "mcp": True, "rag": False, "multi_agent": True}
