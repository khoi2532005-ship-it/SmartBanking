"""Read endpoint: GET /api/alerts (list_alerts) and its validated filters.

Nothing here assumes freshly seeded data: as the post-deploy CRUD check this
runs against a long-lived database that analysts have been working in, or one
that holds no alerts at all. So the module plants three alerts of its own on
a disabled test rule, asserts only on those, and removes them afterwards.
CI's smoke step checks the seed itself."""

import types

import pytest
import requests

from tests.post_commit.helpers import TEST_CUSTOMER, TIMEOUT, new_rule, remove_rule

REQUIRED = {"alert_id", "rule_id", "customer_id", "transaction_id", "transaction_amount", "severity", "status", "created_at"}

PLANTS = [  # created in this order, so their alert ids ascend; the API lists newest first
    {"status": "new", "transaction_amount": 100.0, "transaction_datetime": "2026-01-10T09:00:00",
     "transaction_recipient": "Alpha Pty Ltd", "transaction_category": "groceries"},
    {"status": "reviewed", "transaction_amount": 5000.0, "transaction_datetime": "2026-02-15T12:00:00",
     "transaction_recipient": "Beta Pty Ltd", "transaction_category": "transfer"},
    {"status": "dismissed", "transaction_amount": 9999.5, "transaction_datetime": "2026-03-20T23:30:00",
     "transaction_recipient": "Gamma Pty Ltd", "transaction_category": "travel"},
]


def alerts(api, **params):
    return requests.get(f"{api}/api/alerts", params=params, timeout=5)


@pytest.fixture(scope="module")
def planted(api):
    """A disabled test rule with one alert per PLANTS entry: (rule_id, alert ids oldest first)."""
    r = requests.post(f"{api}/api/rules", json=new_rule(), timeout=TIMEOUT)
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule_id"]
    try:
        ids = []
        for transaction_id, plant in enumerate(PLANTS, start=1):
            r = requests.post(f"{api}/api/alerts", timeout=TIMEOUT, json={
                "rule_id": rule_id, "customer_id": TEST_CUSTOMER, "transaction_id": transaction_id,
                "severity": "high", **plant})
            assert r.status_code == 201, r.text
            ids.append(r.json()["alert_id"])
        yield types.SimpleNamespace(rule_id=rule_id, ids=ids)
    finally:
        remove_rule(api, rule_id)


def test_list_returns_alerts_newest_first(api, planted):
    r = alerts(api)
    assert r.status_code == 200
    rows = r.json()
    ids = [row["alert_id"] for row in rows]
    assert all(REQUIRED <= set(row) for row in rows)
    assert ids == sorted(ids, reverse=True) and set(planted.ids) <= set(ids)


@pytest.mark.parametrize("params, expected", [  # expected: indexes into PLANTS, newest first
    ({}, [2, 1, 0]),
    ({"status": "reviewed"}, [1]),
    ({"customer_id": TEST_CUSTOMER}, [2, 1, 0]),
    ({"min_amount": 5000}, [2, 1]),
    ({"max_amount": 5000}, [1, 0]),
    ({"date_from": "2026-02-15"}, [2, 1]),
    ({"date_to": "2026-02-15"}, [1, 0]),
    ({"q": "Gamma"}, [2]),            # recipient
    ({"q": "transfer"}, [1]),         # category
    ({"status": "new", "max_amount": 100}, [0]),
])
def test_each_filter_returns_exactly_the_matching_alerts(api, planted, params, expected):
    r = alerts(api, rule_id=planted.rule_id, **params)
    assert r.status_code == 200
    assert [row["alert_id"] for row in r.json()] == [planted.ids[i] for i in expected]


def test_a_filter_on_its_own_returns_only_matching_alerts(api, planted):
    rows = alerts(api, status="dismissed").json()
    assert planted.ids[2] in [row["alert_id"] for row in rows]
    assert all(row["status"] == "dismissed" for row in rows)


@pytest.mark.parametrize("params, message", [
    ({"status": "unknown"}, "status must be one of new, reviewed, dismissed, confirmed"),
    ({"min_amount": "abc"}, "min_amount must be a number"),
    ({"customer_id": "0"}, "customer_id must be a positive integer"),
    ({"date_from": "yesterday"}, "date_from must be an ISO date"),
])
def test_unusable_filters_are_400(api, params, message):
    r = alerts(api, **params)
    assert r.status_code == 400 and message in r.json()["error"]
