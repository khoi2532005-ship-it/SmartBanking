"""Endpoint and CRUD checks for a SmartBanking deployment, made through each
feature's frontend.

In the cloud only the frontends are public: every API call goes to the
frontend's own address and its nginx forwards /api/ to the backend. These
checks prove that path works. They run against the local rehearsal stack
(tests/test_cloud_rehearsal.py) and against the deployed Container Apps
(cloud-deployment.yml). Every check is one record in the shape the group's
cloud_deployment_review mode reads: {name, method, url, expected_status, status}.

After a deployment, the whole report in that mode's schema
(docs/deployment/cloud-deployment-report-format.md):

    python deploy/azure/checks.py --outputs reports/cloud/outputs.json \
        --out reports/cloud/cloud-deployment-report.json
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

TIMEOUT = 10

# Per feature: the local rehearsal ports, the page its frontend serves, the
# htmx fragment it loads from its backend outside /api/ (ui_page, if any), whether
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
        "web_port": 3004, "api_port": 5004, "page": "/tabs/budgets.html", "ui_page": "/ui/budgets", "origin_rule": True,
        "crud": {"collection": "/api/budgets",
                 "create": {"customer_id": 1, "category": "Cloud check {tag}", "monthly_limit": 100},
                 "id_path": "budget_id", "update": {"monthly_limit": 150},
                 "create_status": 201, "delete_status": 200},
    },
    "transactions": {
        "web_port": 3005, "api_port": 5005, "page": "/", "ui_page": "/ui/mcp/status", "origin_rule": True,
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
    """The feature's page, its cloud config, its API health and (if it has one)
    its backend htmx fragment, all through the frontend."""
    results = []
    paths = [(f"{feature} page", FEATURES[feature]["page"]), (f"{feature} config", "/config.js"),
             (f"{feature} api health", "/api/health")]
    if "ui_page" in FEATURES[feature]:
        paths.append((f"{feature} ui fragment", FEATURES[feature]["ui_page"]))
    for name, path in paths:
        _check(results, name, "GET", f"{web_url}{path}", 200)
    return results


def crud_checks(feature, web_url):
    """Create, read, update and delete one record through the frontend, then
    confirm it is gone. The delete runs even when the read or update fails."""
    spec = FEATURES[feature]["crud"]
    collection = f"{web_url}{spec['collection']}"
    results = []
    # A browser sends Origin on every write, and three backends refuse a page
    # they do not know: the checks write as that page would.
    origin = {"Origin": web_url}
    created = _check(results, f"{feature} create", "POST", collection, spec["create_status"],
                     json=_fill(spec["create"], uuid.uuid4().hex[:8]), headers=origin)
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
        _check(results, f"{feature} update", "PUT", item, 200, json=spec["update"], headers=origin)
    finally:
        _check(results, f"{feature} delete", "DELETE", item, spec["delete_status"], headers=origin)
    _check(results, f"{feature} read after delete", "GET", item, 404)
    return results


def wait_until_ready(web_urls, timeout=180, interval=5):
    """Polls each frontend's /api/health until it answers 200. A new revision can
    still be starting when the deployment returns. Returns the names that never did."""
    waiting = dict(web_urls)
    deadline = time.monotonic() + timeout
    while waiting:
        for name, url in list(waiting.items()):
            try:
                if requests.get(f"{url}/api/health", timeout=TIMEOUT).status_code == 200:
                    del waiting[name]
            except requests.RequestException:
                pass
        if not waiting or time.monotonic() >= deadline:
            break
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    return sorted(waiting)


SCRIPTS = ["deploy/azure/setup.sh", "deploy/azure/build-images.sh", "deploy/azure/deploy.sh",
           "deploy/azure/main.bicep", "deploy/azure/apps.json"]
AI_SERVICES = ("ai_mode", "mcp", "rag", "multi_agent")


def ai_services(fraud_web_url):
    """The four AI flags as fraud-service reports them; it is the backend whose
    /api/health names all four. "unknown" when they cannot be read."""
    try:
        health = requests.get(f"{fraud_web_url}/api/health", timeout=TIMEOUT).json()
        return {name: "enabled" if health[name]["enabled"] else "disabled" for name in AI_SERVICES}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return dict.fromkeys(AI_SERVICES, "unknown")


def _run_meta():
    """Who, when and which run, from GitHub Actions when there, else the local shell."""
    server, repo, run_id = (os.getenv(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return {
        "region": os.getenv("AZ_LOCATION", "australiaeast"),
        "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": (os.getenv("GITHUB_SHA") or os.getenv("IMAGE_TAG") or "")[:7] or None,
        "deployed_by": os.getenv("GITHUB_ACTOR") or os.getenv("USER"),
        # The bonus profile: deploy.sh turned AI-Mode on (the variable AI_MODE_ENABLED).
        "ai_mode": os.getenv("AI_MODE_ENABLED", "false").strip().lower() == "true",
        # The deployment steps before this one succeeded, or this would not run.
        "workflow": {"name": "cloud-deployment.yml", "run_id": run_id,
                     "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else None,
                     "conclusion": "success" if run_id else None},
    }


def build_report(web_urls, home_url, meta, resources=()):
    """The cloud deployment report: every endpoint and CRUD check, the AI flags,
    and one issue per check that did not return its expected status."""
    endpoints = []
    _check(endpoints, "home page", "GET", f"{home_url}/", 200)
    for feature in FEATURES:
        endpoints += endpoint_checks(feature, web_urls[feature])
    crud = [check for feature in FEATURES for check in crud_checks(feature, web_urls[feature])]
    ai = ai_services(web_urls["fraud"])
    issues = [f"{c['name']}: {c['method']} {c['url']} returned {c['status']}, expected {c['expected_status']}"
              for c in endpoints + crud if c["status"] != c["expected_status"]]
    # The baseline keeps all four AI services off; the bonus profile turns AI-Mode on.
    profile = "bonus" if meta.get("ai_mode") else "baseline"
    wanted = {name: "enabled" if name == "ai_mode" and profile == "bonus" else "disabled" for name in AI_SERVICES}
    issues += [f"{name} is {ai.get(name)}, expected {state} ({profile} profile)"
               for name, state in wanted.items() if ai.get(name) != state]
    return {"schema": "smartbank-cloud-deployment-report/1", "sample": False, "provider": "azure",
            "region": meta["region"], "environment": f"release-2-{profile}", "profile": profile,
            "deployed_at": meta["deployed_at"],
            "commit": meta["commit"], "deployed_by": meta["deployed_by"], "workflow": meta["workflow"],
            "scripts": SCRIPTS, "resources": list(resources), "endpoints": endpoints, "crud_checks": crud,
            "ai_services": ai, "issues": issues}


def results_markdown(report):
    rows = "\n".join(f"| {c['name']} | {c['method']} | {c['url']} | {c['expected_status']} | {c['status']} | "
                      f"{'PASS' if c['status'] == c['expected_status'] else 'FAIL'} |"
                      for c in report["endpoints"] + report["crud_checks"])
    ai = ", ".join(f"{name} {state}" for name, state in report["ai_services"].items())
    issues = "\n".join(f"- {issue}" for issue in report["issues"]) or "- none"
    return (f"# Cloud deployment results\n\nCommit `{report['commit']}`, {report['deployed_at']}, "
            f"run {report['workflow']['run_url'] or 'local'}.\n\nAI services: {ai}.\n\n"
            f"| Check | Method | URL | Expected | Got | Result |\n|---|---|---|---|---|---|\n{rows}\n\n"
            f"## Issues\n\n{issues}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--outputs", required=True, help="deploy.sh's outputs.json: frontends, homeUrl, resources")
    parser.add_argument("--out", required=True, help="where to write the report JSON; the Markdown goes beside it")
    args = parser.parse_args(argv)
    outputs = json.loads(Path(args.outputs).read_text())
    for name in wait_until_ready(outputs["frontends"]):
        print(f"WAIT {name} did not answer /api/health within the wait; checking anyway")
    report = build_report(outputs["frontends"], outputs["homeUrl"], _run_meta(), outputs.get("resources", []))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    out.with_name("deployment-results.md").write_text(results_markdown(report))
    print(f"{len(report['endpoints'])} endpoint checks, {len(report['crud_checks'])} CRUD checks, "
          f"{len(report['issues'])} issue(s); AI services: {report['ai_services']}")
    for issue in report["issues"]:
        print("ISSUE", issue)
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
