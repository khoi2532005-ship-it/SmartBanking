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
        "web_port": 3002, "api_port": 5002, "page": "/", "origin_rule": False,
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


def _check(results, name, method, url, expected_status, timeout=TIMEOUT, **kwargs):
    """Makes one call, appends its record, returns the response (None if the call failed)."""
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
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
# The variable that switches each service on in the bonus profile.
AI_SWITCHES = {"ai_mode": "AI_MODE_ENABLED", "mcp": "MCP_ENABLED", "rag": "RAG_ENABLED",
               "multi_agent": "MULTI_AGENT_ENABLED"}
# In the bonus profile each server that is on must do its real job through the
# application (the fraud frontend and backend), which is what the bonus marks
# ask for: an MCP tool interaction (B2), a grounded RAG answer using retrieved
# context (B3), and a Planner -> Worker -> Reviewer workflow decided by a person
# (B4). A check that answers 200 but not with that is recorded with ok=false
# and an issue, so the report and the cloud review hold the release.
RAG_QUESTION = "What are the four statuses a fraud alert can have?"   # rag_server/corpus/fraud-alerts-feature.md answers it
ALERT_STATUSES = ("new", "reviewed", "dismissed", "confirmed")
WORKFLOW_TASK = "How many fraud alerts does this customer have, by status?"
WORKFLOW_WAIT = 300        # seconds for the three agents to reach the human gate
WORKFLOW_POLL = 5
POLL_FAILURES = 3          # 5xx replies in a row that end the wait for the gate
RAG_TIMEOUT = 100          # fraud's backend waits 90 s for the RAG server (Gemini writes the answer)
AI_WAIT = 120              # seconds an AI server may still be starting after the deployment
AI_RETRY = 5
GATE = "awaiting_human_review"
ENDED = ("accepted", "partially_accepted", "rejected", "failed")


def _starting(response):
    """No reply, or a 5xx from the backend that is not "switched off": the AI server
    behind it is probably still starting, which a cold deployment makes likely."""
    if response is None:
        return True
    if response.status_code < 500:
        return False
    try:
        body = response.json()
    except ValueError:
        return True
    return not (isinstance(body, dict) and body.get("disabled"))


def _interaction(records, issues, name, method, url, expected_status, verdict, wait=0, **kwargs):
    """One check whose body matters: `verdict(body)` returns (ok, detail) for a reply
    with the expected status; a wrong status is left to build_report's issue. With
    `wait` (a server's first call), a server that is still starting is retried for that
    many seconds; only the last try is recorded."""
    deadline = time.monotonic() + wait
    while True:
        tries = []
        response = _check(tries, name, method, url, expected_status, **kwargs)
        if not _starting(response) or time.monotonic() >= deadline:
            break
        time.sleep(AI_RETRY)
    records.append(tries[-1])
    record = records[-1]
    body = None
    if response is not None and response.status_code == expected_status:
        try:
            body = response.json()
        except ValueError:
            body = None
        ok, detail = verdict(body if isinstance(body, dict) else {})
    else:
        ok, detail = False, "no reply" if response is None else f"HTTP {response.status_code}"
    record["ok"], record["detail"] = ok, detail
    if not ok and response is not None and response.status_code == expected_status:
        issues.append(f"{name}: {detail}")
    return ok, body if isinstance(body, dict) else {}


def _mcp_interaction(records, issues, base):
    _interaction(records, issues, "fraud mcp tools", "GET", f"{base}/api/mcp/tools", 200,
                 lambda b: (bool(b.get("tools")), f"{b.get('tool_count', len(b.get('tools') or []))} tools listed"),
                 wait=AI_WAIT)
    # fraud's own tool, called by its backend over MCP; an empty body counts every alert.
    _interaction(records, issues, "fraud mcp tool call", "POST", f"{base}/api/mcp/tool", 200,
                 lambda b: (bool(b.get("result")), f"{b.get('tool')} -> {json.dumps(b.get('result'))[:120]}"
                            if b.get("result") else "the reply carries no tool result"), json={})


def _rag_interaction(records, issues, base):
    def verdict(b):
        if b.get("insufficient_context") or not b.get("citations"):
            return False, "the RAG server found no relevant document (insufficient context), so nothing was grounded"
        # Citations alone do not prove the retrieved context was used: the answer
        # must name the statuses the cited document lists.
        named = sum(1 for s in ALERT_STATUSES if s in str(b.get("answer", "")).lower())
        if named < len(ALERT_STATUSES):
            return False, f"grounded, but the answer names {named} of the {len(ALERT_STATUSES)} statuses the document lists"
        return True, (f"grounded, {len(b['citations'])} citation(s), confidence {b.get('confidence_category')}, "
                      f"names all {len(ALERT_STATUSES)} statuses")
    _interaction(records, issues, "fraud rag query", "POST", f"{base}/api/rag/query", 200, verdict,
                 json={"query": RAG_QUESTION}, timeout=RAG_TIMEOUT, wait=AI_WAIT)


def _multi_agent_interaction(records, issues, base):
    ok, started = _interaction(records, issues, "fraud multi-agent start", "POST", f"{base}/api/agents/workflow", 202,
                               lambda b: (bool(b.get("workflow_id")), f"workflow {b.get('workflow_id')} started"),
                               json={"task": WORKFLOW_TASK, "customer_id": 1}, wait=AI_WAIT)
    if not ok:
        return
    workflow = f"{base}/api/agents/workflow/{started['workflow_id']}"
    # Follow the workflow to the human gate (Planner, Worker, Reviewer each have a stage timeout).
    deadline = time.monotonic() + WORKFLOW_WAIT
    body, failures = {}, 0
    while True:
        # Polled through _check into a throwaway list: the same call as every
        # check, but only the last look (below) goes into the report.
        response = _check([], "fraud multi-agent poll", "GET", workflow, 200)
        if response is not None and response.status_code == 404:
            break                  # the backend no longer knows this workflow: nothing to wait for
        failures = failures + 1 if response is None or response.status_code >= 500 else 0
        if failures >= POLL_FAILURES:
            break
        try:
            body = response.json() if response is not None else {}
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        if body.get("state") == GATE or body.get("state") in ENDED or time.monotonic() >= deadline:
            break
        time.sleep(WORKFLOW_POLL)

    def at_gate(b):
        state = b.get("state")
        if state == GATE:
            return True, "Planner, Worker and Reviewer completed; awaiting the human decision"
        if state in ENDED:
            return False, f"the workflow ended in state {state} ({b.get('error') or 'no error recorded'})"
        return False, f"the workflow was still {state or 'unknown'} after {WORKFLOW_WAIT}s"
    ok, _ = _interaction(records, issues, "fraud multi-agent gate", "GET", workflow, 200, at_gate)
    if not ok:
        return
    ok, _ = _interaction(records, issues, "fraud multi-agent decision", "POST", f"{workflow}/review", 200,
                         lambda b: (True, "accepted; state accepted") if b.get("state") == "accepted"
                         else (False, f"the decision was not recorded (state {b.get('state')})"),
                         json={"decision": "accept", "note": "", "reviewer": "cloud-deployment.yml"})
    if not ok:
        return
    _interaction(records, issues, "fraud multi-agent release", "GET", workflow, 200,
                 lambda b: (bool((b.get("final_response") or {}).get("released")),
                            "final response released after the decision" if (b.get("final_response") or {}).get("released")
                            else "the final response was not released"))


def ai_interactions(fraud_web_url, requested):
    """(check records, issues) for every AI service the deployment was asked to turn on."""
    records, issues = [], []
    for name, interaction in (("mcp", _mcp_interaction), ("rag", _rag_interaction), ("multi_agent", _multi_agent_interaction)):
        if requested.get(name):
            interaction(records, issues, fraud_web_url)
    return records, issues


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
        # The bonus profile: the services deploy.sh was asked to turn on.
        "requested": {name: os.getenv(var, "false").strip().lower() == "true" for name, var in AI_SWITCHES.items()},
        # The deployment steps before this one succeeded, or this would not run.
        "workflow": {"name": "cloud-deployment.yml", "run_id": run_id,
                     "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else None,
                     "conclusion": "success" if run_id else None},
    }


def build_report(web_urls, home_url, meta, resources=()):
    """The cloud deployment report: every endpoint and CRUD check, the AI flags,
    and one issue per check that did not return its expected status."""
    requested = meta.get("requested") or {}
    endpoints = []
    _check(endpoints, "home page", "GET", f"{home_url}/", 200)
    for feature in FEATURES:
        endpoints += endpoint_checks(feature, web_urls[feature])
    interactions, interaction_issues = ai_interactions(web_urls["fraud"], requested)
    endpoints += interactions
    crud = [check for feature in FEATURES for check in crud_checks(feature, web_urls[feature])]
    ai = ai_services(web_urls["fraud"])
    issues = [f"{c['name']}: {c['method']} {c['url']} returned {c['status']}, expected {c['expected_status']}"
              for c in endpoints + crud if c["status"] != c["expected_status"]]
    issues += interaction_issues
    # The baseline keeps all four AI services off; the bonus profile turns on the ones asked for.
    profile = "bonus" if any(requested.values()) else "baseline"
    wanted = {name: "enabled" if requested.get(name) else "disabled" for name in AI_SERVICES}
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
                      f"{'PASS' if c['status'] == c['expected_status'] and c.get('ok') is not False else 'FAIL'} |"
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
