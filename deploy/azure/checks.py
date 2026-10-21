"""Endpoint and CRUD checks for a SmartBanking deployment, made through each
feature's frontend.

In the cloud only the frontends are public: every API call goes to the
frontend's own address and its nginx forwards /api/ to the backend. These
checks prove that path works. They run against the local rehearsal stack
(tests/test_cloud_rehearsal.py) and against the deployed Container Apps
(cloud-deployment.yml). Every check is one record in the shape the group's
cloud_deployment_review mode reads: {name, method, url, expected_status, status}.
"""

import uuid

import requests

TIMEOUT = 10

# Per feature: the local rehearsal ports, the page its frontend serves, whether
# its backend checks the browser origin (and so needs *_FRONTEND_ORIGINS), and
# one create-read-update-delete cycle. "{tag}" in a create body becomes a fresh
# id, so a check never collides with real data or with an earlier run.
FEATURES = {
    "accounts": {
        "web_port": 3001, "api_port": 5001, "page": "/", "origin_rule": False,
        "crud": {"collection": "/api/customers",
                 "create": {"first_name": "Cloud", "last_name": "Check", "email": "cloud-check-{tag}@example.com"},
                 "id_path": "customer_id", "update": {"phone": "0400000000"},
                 "create_status": 201, "delete_status": 200},
    },
    "loans": {
        "web_port": 3002, "api_port": 5002, "page": "/tabs/loans.html", "origin_rule": False,
        "crud": {"collection": "/api/loans",
                 "create": {"customer_id": 1, "loan_type": "PERSONAL", "requested_amount": 5000,
                            "loan_purpose": "cloud check"},
                 "id_path": "loan.loan_id", "update": {"loan_purpose": "cloud check updated"},
                 "create_status": 201, "delete_status": 200},
    },
    "fraud": {
        "web_port": 3003, "api_port": 5003, "page": "/tabs/normal.html", "origin_rule": True,
        "crud": {"collection": "/api/rules",
                 "create": {"rule_name": "release-check {tag}", "rule_type": "amount_over",
                            "threshold_value": 7500, "severity": "high", "enabled": False},
                 "id_path": "rule_id", "update": {"severity": "medium"},
                 "create_status": 201, "delete_status": 200},
    },
    "budgeting": {
        "web_port": 3004, "api_port": 5004, "page": "/tabs/budgets.html", "origin_rule": True,
        "crud": {"collection": "/api/budgets",
                 "create": {"customer_id": 1, "category": "Cloud check {tag}", "monthly_limit": 100},
                 "id_path": "budget_id", "update": {"monthly_limit": 150},
                 "create_status": 201, "delete_status": 200},
    },
    "transactions": {
        "web_port": 3005, "api_port": 5005, "page": "/", "origin_rule": True,
        "crud": {"collection": "/api/transactions",
                 "create": {"account_id": 1, "amount": 12.5, "currency": "AUD", "type": "Deposit",
                            "date": "2026-10-01", "description": "cloud check"},
                 "id_path": "transaction_id", "update": {"description": "cloud check updated"},
                 "create_status": 201, "delete_status": 200},
    },
}


def _check(results, name, method, url, expected_status, **kwargs):
    """Makes one call, appends its record, returns the response (None if the call failed)."""
    try:
        response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException:
        response = None
    results.append({"name": name, "method": method, "url": url, "expected_status": expected_status,
                    "status": response.status_code if response is not None else None})
    return response


def _fill(body, tag):
    return {key: value.replace("{tag}", tag) if isinstance(value, str) else value for key, value in body.items()}


def _dig(data, path):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def endpoint_checks(feature, web_url):
    """The feature's page, its cloud config and its API health, all through the frontend."""
    results = []
    for name, path in ((f"{feature} page", FEATURES[feature]["page"]), (f"{feature} config", "/config.js"),
                       (f"{feature} api health", "/api/health")):
        _check(results, name, "GET", f"{web_url}{path}", 200)
    return results


def crud_checks(feature, web_url):
    """Create, read, update and delete one record through the frontend, then
    confirm it is gone. The delete runs even when the read or update fails."""
    spec = FEATURES[feature]["crud"]
    collection = f"{web_url}{spec['collection']}"
    results = []
    created = _check(results, f"{feature} create", "POST", collection, spec["create_status"],
                     json=_fill(spec["create"], uuid.uuid4().hex[:8]))
    if created is None or created.status_code != spec["create_status"]:
        return results
    try:
        item_id = _dig(created.json(), spec["id_path"])
    except ValueError:
        item_id = None
    if item_id is None:
        results.append({"name": f"{feature} create returns {spec['id_path']}", "method": "POST", "url": collection,
                        "expected_status": spec["create_status"], "status": None})
        return results
    item = f"{collection}/{item_id}"
    try:
        _check(results, f"{feature} read", "GET", item, 200)
        _check(results, f"{feature} update", "PUT", item, 200, json=spec["update"])
    finally:
        _check(results, f"{feature} delete", "DELETE", item, spec["delete_status"])
    _check(results, f"{feature} read after delete", "GET", item, 404)
    return results
