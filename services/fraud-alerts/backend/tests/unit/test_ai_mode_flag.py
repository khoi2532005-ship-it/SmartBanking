"""AI_MODE_ENABLED: Explain answers 503 when it is off, detection still writes
alerts without calling the LLM, and /api/health says which way it is set."""

from routes import ai as ai_routes
from services import database_api, explain
from tests.unit.helpers import ALERT, RULE, FakeResponse

EXPLANATION = "Large Transaction Alert: $7,500 is over $5,000."


def never(*args, **kwargs):
    raise AssertionError("must not be called while AI-Mode is off")


def test_explain_is_503_when_ai_mode_is_off(client, monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    monkeypatch.setattr(database_api, "get_alert_response", never)
    r = client.get("/api/ai/alerts/1/explain")
    assert r.status_code == 503
    assert r.get_json() == {"error": "AI-Mode is switched off in this environment (AI_MODE_ENABLED=false)", "disabled": True}


def test_explain_still_works_when_ai_mode_is_on(client, monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "true")
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(database_api, "get_alert_response", lambda alert_id: FakeResponse(200, ALERT))
    monkeypatch.setattr(database_api, "get_rule", lambda rule_id: RULE)
    monkeypatch.setattr(database_api, "update_alert", lambda alert_id, payload: {})
    monkeypatch.setattr(ai_routes, "generate_explanation", lambda alert, rule, history: (EXPLANATION, False))
    body = client.get("/api/ai/alerts/1/explain").get_json()
    assert (body["explanation"], body["degraded"]) == (EXPLANATION, False)


def test_detection_writes_alerts_without_the_llm_when_ai_mode_is_off(client, monkeypatch, detection_world):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    monkeypatch.setattr(explain, "create_chat_completion", never)
    monkeypatch.setattr(explain.account_context, "fetch_account_context", never)
    body = client.post("/api/detection/run").get_json()
    assert (body["new_alert_count"], body["explanations_skipped"]) == (1, 1)
    assert "ai_explanation" not in body["new_alerts"][0] and detection_world.updates == []


def test_health_reports_ai_mode(client, monkeypatch):
    monkeypatch.setenv("AI_MODE_ENABLED", "false")
    ai_mode = client.get("/api/health").get_json()["ai_mode"]
    assert ai_mode["enabled"] is False and ai_mode["provider"] in ("gemini", "ollama")
