"""An explanation that cannot be saved is still returned, and the failure is logged, not swallowed."""

import logging

from routes import ai as ai_routes, detection as detection_routes
from services import database_api
from tests.unit.helpers import ALERT, RULE, FakeResponse

EXPLANATION = "Large Transaction Alert: $7,500 is over $5,000."


def fail(*args, **kwargs):
    raise RuntimeError("fraud-database-service went away")


def test_explain_logs_an_explanation_it_could_not_save(client, monkeypatch, caplog):
    monkeypatch.setenv("AI_MODE_ENABLED", "true")
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setattr(database_api, "get_alert_response", lambda alert_id: FakeResponse(200, ALERT))
    monkeypatch.setattr(database_api, "get_rule", lambda rule_id: RULE)
    monkeypatch.setattr(database_api, "update_alert", fail)
    monkeypatch.setattr(ai_routes, "generate_explanation", lambda alert, rule, history: (EXPLANATION, False))
    with caplog.at_level(logging.WARNING):
        body = client.get("/api/ai/alerts/1/explain").get_json()
    assert body["explanation"] == EXPLANATION and "alert 1 was not saved" in caplog.text


def test_detection_logs_an_explanation_it_could_not_save(client, monkeypatch, caplog, detection_world):
    monkeypatch.setenv("AI_MODE_ENABLED", "true")
    monkeypatch.setattr(detection_routes, "generate_explanation", lambda alert, rule: (EXPLANATION, False))
    monkeypatch.setattr(database_api, "update_alert", fail)
    with caplog.at_level(logging.WARNING):
        body = client.post("/api/detection/run").get_json()
    assert body["new_alerts"][0]["ai_explanation"] == EXPLANATION and "alert 99 was not saved" in caplog.text
