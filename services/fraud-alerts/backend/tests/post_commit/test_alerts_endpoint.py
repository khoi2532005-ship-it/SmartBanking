"""Read endpoint: GET /api/alerts (list_alerts) and its validated filters.

Nothing here assumes freshly seeded data: as the post-deploy CRUD check this
runs against a long-lived database that analysts have been working in. CI's
smoke step checks the seed itself."""

import pytest
import requests

REQUIRED = {"alert_id", "rule_id", "customer_id", "transaction_id", "transaction_amount", "severity", "status", "created_at"}


def alerts(api, **params):
    return requests.get(f"{api}/api/alerts", params=params, timeout=5)


def test_list_returns_alerts_newest_first(api):
    r = alerts(api)
    assert r.status_code == 200
    rows = r.json()
    assert rows and all(REQUIRED <= set(row) for row in rows)
    assert [row["alert_id"] for row in rows] == sorted((row["alert_id"] for row in rows), reverse=True)


@pytest.mark.parametrize("field", ["status", "customer_id"])
def test_filters_return_exactly_the_matching_alerts(api, field):
    everything = alerts(api).json()
    assert everything, "no alerts to filter: the database holds none"
    value = everything[0][field]  # a value the data actually has
    matching = alerts(api, **{field: value}).json()
    assert matching and all(row[field] == value for row in matching)
    assert len(matching) == sum(1 for row in everything if row[field] == value)


@pytest.mark.parametrize("params, message", [
    ({"status": "unknown"}, "status must be one of new, reviewed, dismissed, confirmed"),
    ({"min_amount": "abc"}, "min_amount must be a number"),
    ({"customer_id": "0"}, "customer_id must be a positive integer"),
    ({"date_from": "yesterday"}, "date_from must be an ISO date"),
])
def test_unusable_filters_are_400(api, params, message):
    r = alerts(api, **params)
    assert r.status_code == 400 and message in r.json()["error"]
