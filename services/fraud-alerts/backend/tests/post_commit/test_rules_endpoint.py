"""Write endpoint: POST /api/rules (submit_rule), through a full
create-read-update-delete cycle. That cycle is also fraud's post-deploy CRUD
check, so every rule it creates is deleted again, even when an assertion fails,
and a rule an interrupted run left behind is swept at the start of the next."""

import pytest
import requests

from tests.post_commit.helpers import TEST_CUSTOMER, TIMEOUT, new_rule, remove_rule, sweep_leftovers


def stored(api, rule_id):
    return requests.get(f"{api}/api/rules/{rule_id}", timeout=5)


@pytest.fixture
def created(api):
    """Ids of the rules a test created; each one is removed afterwards."""
    ids = []
    yield ids
    for rule_id in ids:
        remove_rule(api, rule_id)


def test_rule_crud_cycle(api, created):
    r = requests.post(f"{api}/api/rules", json=new_rule(), timeout=5)
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule_id"]
    created.append(rule_id)
    row = stored(api, rule_id).json()
    assert (row["rule_type"], row["threshold_value"], row["threshold_secondary"], row["severity"], row["enabled"]) == \
           ("amount_over", 7500, None, "high", 0)
    assert requests.put(f"{api}/api/rules/{rule_id}", json={"severity": "medium", "enabled": True}, timeout=5).status_code == 200
    row = stored(api, rule_id).json()
    assert (row["severity"], row["enabled"]) == ("medium", 1)
    assert requests.delete(f"{api}/api/rules/{rule_id}", timeout=5).status_code == 200
    created.remove(rule_id)
    assert stored(api, rule_id).status_code == 404


@pytest.mark.parametrize("body, message", [
    (new_rule(rule_name="  "), "rule_name is required"),
    (new_rule(rule_type="sometimes"), "rule_type must be one of"),
    (new_rule(rule_type="velocity", threshold_value=3), "velocity needs threshold_secondary"),
    (new_rule(rule_type="unusual_time", threshold_value=3, threshold_secondary=3), "start and end hours must differ"),
    (new_rule(threshold_value="NaN"), "threshold_value must be a finite number"),
])
def test_invalid_rules_are_400_and_store_nothing(api, body, message):
    r = requests.post(f"{api}/api/rules", json=body, timeout=5)
    assert r.status_code == 400 and message in r.json()["error"]
    # By name, not by counting rows: an analyst may add a rule while this runs.
    names = [rule["rule_name"].strip() for rule in requests.get(f"{api}/api/rules", timeout=5).json()]
    assert body["rule_name"].strip() not in names


def test_form_posts_are_400(api):
    r = requests.post(f"{api}/api/rules", data="rule_name=x", timeout=5,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 400 and r.json()["error"] == "JSON body required"


def test_sweep_removes_what_an_interrupted_run_left(api):
    rule_id = requests.post(f"{api}/api/rules", json=new_rule(), timeout=TIMEOUT).json()["rule_id"]
    alert = {"rule_id": rule_id, "customer_id": TEST_CUSTOMER, "transaction_id": 1,
             "transaction_amount": 7500, "severity": "high"}
    assert requests.post(f"{api}/api/alerts", json=alert, timeout=TIMEOUT).status_code == 201
    assert rule_id in sweep_leftovers(api)
    assert stored(api, rule_id).status_code == 404
    assert requests.get(f"{api}/api/alerts", params={"rule_id": rule_id}, timeout=TIMEOUT).json() == []
