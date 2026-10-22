"""The records the post-commit tests create, and how they are removed again.

The same suite is fraud's CRUD check against the deployed backend, so
everything it creates is marked and kept away from real work: rule names
start with TEST_PREFIX, rules are created disabled so a leftover never fires
in Detection, and alerts belong to TEST_CUSTOMER, which no real customer is.
An interrupted run can still leave records behind; sweep_leftovers() removes
them at the start of the next one.
"""

import uuid

import requests

TEST_PREFIX = "release-check "
TEST_CUSTOMER = 999999
TIMEOUT = 5


def new_rule(**changes):
    return {"rule_name": f"{TEST_PREFIX}{uuid.uuid4().hex[:8]}", "rule_type": "amount_over",
            "threshold_value": 7500, "severity": "high", "enabled": False, **changes}


def _listed(api, path, params=None):
    """A list endpoint's rows. /api/health never touches the database, so an
    outage first shows here: say what the API answered, not a TypeError."""
    r = requests.get(f"{api}{path}", params=params, timeout=TIMEOUT)
    assert r.status_code == 200, f"GET {path} answered HTTP {r.status_code}: {r.text.strip()}"
    return r.json()


def remove_rule(api, rule_id):
    """Deletes the rule's alerts, then the rule: a rule that still has alerts
    cannot be deleted (409). 404 counts as done, so a test that already
    removed it is not an error; anything else fails the teardown.

    An alert on any customer but TEST_CUSTOMER means the rule fired on real
    data (the suite's rules were once created enabled). Those alerts may carry
    an analyst's work, so they are left for a person instead of deleted."""
    alerts = _listed(api, "/api/alerts", {"rule_id": rule_id})
    real = sorted({alert["customer_id"] for alert in alerts if alert["customer_id"] != TEST_CUSTOMER})
    assert not real, (f"test rule {rule_id} has alerts on customers {real}: it fired on real data, "
                      f"so it is left for a person to review and delete")
    for alert in alerts:
        status = requests.delete(f"{api}/api/alerts/{alert['alert_id']}", timeout=TIMEOUT).status_code
        assert status in (200, 404), f"alert {alert['alert_id']} of test rule {rule_id} was not removed (HTTP {status})"
    status = requests.delete(f"{api}/api/rules/{rule_id}", timeout=TIMEOUT).status_code
    assert status in (200, 404), f"test rule {rule_id} was not removed (HTTP {status})"


def sweep_leftovers(api):
    """Removes every test rule (and its alerts) still in the database. Returns their ids."""
    leftovers = [rule["rule_id"] for rule in _listed(api, "/api/rules") if rule["rule_name"].startswith(TEST_PREFIX)]
    for rule_id in leftovers:
        remove_rule(api, rule_id)
    return leftovers
