"""deploy/azure/checks.py's report: the AI services must be what the deployment
asked for. The baseline keeps all four off; with AI_MODE_ENABLED=true (the
bonus profile) AI-Mode must be on and the other three still off."""

import pytest

from deploy.azure import checks

ALL_OFF = dict.fromkeys(checks.AI_SERVICES, "disabled")
META = {"region": "r", "deployed_at": "t", "commit": "c", "deployed_by": "u", "workflow": {}}


@pytest.fixture
def report(monkeypatch):
    """build_report with no HTTP: no endpoint or CRUD checks, the given AI states."""
    monkeypatch.setattr(checks, "_check", lambda *args: None)
    monkeypatch.setattr(checks, "endpoint_checks", lambda feature, url: [])
    monkeypatch.setattr(checks, "crud_checks", lambda feature, url: [])

    def build(states, ai_mode):
        monkeypatch.setattr(checks, "ai_services", lambda url: states)
        urls = dict.fromkeys(checks.FEATURES, "https://x")
        return checks.build_report(urls, "https://home", {**META, "ai_mode": ai_mode})
    return build


def test_the_baseline_wants_all_four_off(report):
    r = report(ALL_OFF, ai_mode=False)
    assert (r["profile"], r["issues"]) == ("baseline", [])
    assert report({**ALL_OFF, "ai_mode": "enabled"}, ai_mode=False)["issues"] == [
        "ai_mode is enabled, expected disabled (baseline profile)"]


def test_the_bonus_profile_wants_ai_mode_on_and_the_rest_off(report):
    r = report({**ALL_OFF, "ai_mode": "enabled"}, ai_mode=True)
    assert (r["profile"], r["issues"]) == ("bonus", [])
    assert report(ALL_OFF, ai_mode=True)["issues"] == ["ai_mode is disabled, expected enabled (bonus profile)"]
    assert report({**ALL_OFF, "ai_mode": "enabled", "mcp": "enabled"}, ai_mode=True)["issues"] == [
        "mcp is enabled, expected disabled (bonus profile)"]


def test_the_run_says_whether_ai_mode_was_asked_for(monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "true")
    assert checks._run_meta()["ai_mode"] is True
    monkeypatch.delenv("AI_MODE_ENABLED")
    assert checks._run_meta()["ai_mode"] is False
