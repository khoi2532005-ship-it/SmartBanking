import os

import requests


FRAUD_DB_URL = os.getenv("FRAUD_DB_URL", "http://localhost:5013")
TIMEOUT = 5


def _params(query):
    return {k: v for k, v in (query or {}).items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

def search_rules(filters=None):
    response = requests.get(f"{FRAUD_DB_URL}/rules", params=_params(filters), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_rule_response(rule_id):
    return requests.get(f"{FRAUD_DB_URL}/rules/{rule_id}", timeout=TIMEOUT)


def get_rule(rule_id):
    response = get_rule_response(rule_id)
    response.raise_for_status()
    return response.json()


def create_rule(payload):
    response = requests.post(f"{FRAUD_DB_URL}/rules", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def update_rule(rule_id, payload):
    response = requests.put(f"{FRAUD_DB_URL}/rules/{rule_id}", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def delete_rule(rule_id):
    response = requests.delete(f"{FRAUD_DB_URL}/rules/{rule_id}", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def search_alerts(filters=None):
    response = requests.get(f"{FRAUD_DB_URL}/alerts", params=_params(filters), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_alert_response(alert_id):
    return requests.get(f"{FRAUD_DB_URL}/alerts/{alert_id}", timeout=TIMEOUT)


def get_alert(alert_id):
    response = get_alert_response(alert_id)
    response.raise_for_status()
    return response.json()


def create_alert_response(payload):
    """Returns the raw response so callers (e.g. detection) can tell a 409
    duplicate (already alerted for this rule+transaction) from a real error."""
    return requests.post(f"{FRAUD_DB_URL}/alerts", json=payload, timeout=TIMEOUT)


def update_alert(alert_id, payload):
    response = requests.put(f"{FRAUD_DB_URL}/alerts/{alert_id}", json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def delete_alert(alert_id):
    response = requests.delete(f"{FRAUD_DB_URL}/alerts/{alert_id}", timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()
