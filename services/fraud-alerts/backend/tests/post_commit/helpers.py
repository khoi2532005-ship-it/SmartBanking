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


def remove_rule(api, rule_id):
    """Deletes the rule's alerts, then the rule: a rule that still has alerts
    cannot be deleted (409). 404 counts as done, so a test that already
    removed it is not an error; anything else fails the teardown."""
    for alert in requests.get(f"{api}/api/alerts", params={"rule_id": rule_id}, timeout=TIMEOUT).json():
        status = requests.delete(f"{api}/api/alerts/{alert['alert_id']}", timeout=TIMEOUT).status_code
        assert status in (200, 404), f"alert {alert['alert_id']} of test rule {rule_id} was not removed (HTTP {status})"
    status = requests.delete(f"{api}/api/rules/{rule_id}", timeout=TIMEOUT).status_code
    assert status in (200, 404), f"test rule {rule_id} was not removed (HTTP {status})"


def sweep_leftovers(api):
    """Removes every test rule (and its alerts) still in the database. Returns their ids."""
    rules = requests.get(f"{api}/api/rules", timeout=TIMEOUT).json()
    leftovers = [rule["rule_id"] for rule in rules if rule["rule_name"].startswith(TEST_PREFIX)]
    for rule_id in leftovers:
        remove_rule(api, rule_id)
    return leftovers
