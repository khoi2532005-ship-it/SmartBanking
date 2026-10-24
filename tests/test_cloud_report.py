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


def test_a_server_that_is_on_must_answer_through_the_application(report):
    # The flag only says the backend will try; a call through the fraud
    # frontend proves the backend reaches the server: an MCP tools/list, and
    # the Multi-Agent Server's workflow list (with the bearer token).
    calls = lambda r: [(e["method"], e["url"]) for e in r["endpoints"] if e["name"].startswith("fraud ")]  # noqa: E731
    assert calls(report(ALL_OFF)) == []
    on = {**ALL_OFF, "mcp": "enabled", "multi_agent": "enabled"}
    assert calls(report(on, mcp=True, multi_agent=True)) == [("GET", "https://x/api/mcp/tools"),
                                                             ("GET", "https://x/api/agents/workflows")]
    # RAG answers a question: a POST with a query, and "insufficient context"
    # is still a 200 from the server, so this proves the backend reaches it.
    assert calls(report({**ALL_OFF, "rag": "enabled"}, rag=True)) == [("POST", "https://x/api/rag/query")]


def test_the_run_says_which_services_were_asked_for(monkeypatch):
    for name in ("AI_MODE_ENABLED", "MCP_ENABLED", "RAG_ENABLED", "MULTI_AGENT_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "TRUE")
    assert checks._run_meta()["requested"] == {"ai_mode": False, "mcp": True, "rag": False, "multi_agent": True}
