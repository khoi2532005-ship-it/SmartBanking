"""The AI Mode tab: the Multi-Agent panel is wired to fraud-service, and only to fraud-service."""

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[3] / "frontend" / "templates" / "tabs" / "ai-mode.html").read_text(encoding="utf-8")


def test_panel_is_wired_to_the_fraud_routes():
    for needle in ('id="ma-form"', 'id="ma-result"', 'id="ma-history"', "/api/agents/workflow", "/api/agents/workflows",
                   "/review", '"partially_accept"', "Partially accept (correct)", "data-decision", "data-task"):
        assert needle in HTML, needle


def test_no_shared_server_is_called_from_the_browser_and_release_1_panels_stay():
    for port in (":8100", ":8200", ":8300", ":11434"):
        assert port not in HTML, port
    for needle in ('id="explain-form"', 'id="mcp-form"', 'id="rag-form"'):
        assert needle in HTML, needle


def test_the_reviewer_name_is_required():
    assert re.search(r'<input id="ma_reviewer"[^>]*\brequired\b', HTML)
