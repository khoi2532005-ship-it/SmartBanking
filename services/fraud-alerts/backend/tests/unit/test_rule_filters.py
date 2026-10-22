"""GET /api/rules filters: a value that cannot match is a 400, never a quietly
wrong list (enabled=yes used to list the disabled rules)."""

import pytest

from services import database_api


@pytest.fixture
def searched(monkeypatch):
    seen = []
    monkeypatch.setattr(database_api, "search_rules", lambda filters: seen.append(filters) or [])
    return seen


@pytest.mark.parametrize("query, filters", [
    ("", {}),
    ("?rule_type=VELOCITY&enabled=true", {"rule_type": "velocity", "enabled": 1}),
    ("?enabled=0", {"enabled": 0}),
    ("?enabled=&rule_type=", {}),
])
def test_rule_filters_reach_the_database_cleaned(client, searched, query, filters):
    assert client.get(f"/api/rules{query}").status_code == 200 and searched == [filters]


@pytest.mark.parametrize("query, message", [
    ("?enabled=yes", "enabled must be true/false or 1/0"),
    ("?rule_type=velocty", "rule_type must be one of amount_over, velocity, unusual_time, new_recipient_high_value"),
])
def test_a_rule_filter_that_cannot_match_is_400(client, searched, query, message):
    r = client.get(f"/api/rules{query}")
    assert (r.status_code, r.get_json()["error"]) == (400, message) and searched == []
