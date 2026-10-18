"""Write endpoint: POST /api/rules (submit_rule), through a full
create-read-update-delete cycle. That cycle is also fraud's post-deploy CRUD
check, so every rule it creates is deleted again, even when an assertion fails."""

import uuid

import pytest
import requests


def rule(**changes):
    return {"rule_name": f"release-check {uuid.uuid4().hex[:8]}", "rule_type": "amount_over",
            "threshold_value": 7500, "severity": "high", "enabled": True, **changes}


def stored(api, rule_id):
    return requests.get(f"{api}/api/rules/{rule_id}", timeout=5)


@pytest.fixture
def created(api):
    """Ids of the rules a test created; each one is deleted afterwards."""
    ids = []
    yield ids
    for rule_id in ids:
        requests.delete(f"{api}/api/rules/{rule_id}", timeout=5)


def test_rule_crud_cycle(api, created):
    r = requests.post(f"{api}/api/rules", json=rule(), timeout=5)
    assert r.status_code == 201, r.text
    rule_id = r.json()["rule_id"]
    created.append(rule_id)
    row = stored(api, rule_id).json()
    assert (row["rule_type"], row["threshold_value"], row["threshold_secondary"], row["severity"], row["enabled"]) == \
           ("amount_over", 7500, None, "high", 1)
    assert requests.put(f"{api}/api/rules/{rule_id}", json={"severity": "medium", "enabled": False}, timeout=5).status_code == 200
    row = stored(api, rule_id).json()
    assert (row["severity"], row["enabled"]) == ("medium", 0)
    assert requests.delete(f"{api}/api/rules/{rule_id}", timeout=5).status_code == 200
    created.remove(rule_id)
    assert stored(api, rule_id).status_code == 404


@pytest.mark.parametrize("body, message", [
    (rule(rule_name="  "), "rule_name is required"),
    (rule(rule_type="sometimes"), "rule_type must be one of"),
    (rule(rule_type="velocity", threshold_value=3), "velocity needs threshold_secondary"),
    (rule(rule_type="unusual_time", threshold_value=3, threshold_secondary=3), "start and end hours must differ"),
    (rule(threshold_value="NaN"), "threshold_value must be a finite number"),
])
def test_invalid_rules_are_400_and_store_nothing(api, body, message):
    before = len(requests.get(f"{api}/api/rules", timeout=5).json())
    r = requests.post(f"{api}/api/rules", json=body, timeout=5)
    assert r.status_code == 400 and message in r.json()["error"]
    assert len(requests.get(f"{api}/api/rules", timeout=5).json()) == before


def test_form_posts_are_400(api):
    r = requests.post(f"{api}/api/rules", data="rule_name=x", timeout=5,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 400 and r.json()["error"] == "JSON body required"
