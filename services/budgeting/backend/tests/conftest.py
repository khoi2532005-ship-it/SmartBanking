"""Writes the post-commit endpoint test report when ENDPOINT_REPORT_DIR is set.

Only the endpoint test module is reported; the other modules in this folder are
plain-runner checks and are not collected by pytest in CI.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404  # local git metadata only
import time
from datetime import datetime, timezone
from pathlib import Path

MODULE = "test_endpoints_post_commit"
_results: list[dict] = []


def _git_sha() -> str:
    """The short commit id: long enough to find the commit, short enough that
    detect-secrets does not read it as a high-entropy string in the report."""
    if os.getenv("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:7]
    try:
        return subprocess.check_output(  # noqa: S603  # constant executable, repo-local
            ["git", "rev-parse", "--short=7", "HEAD"], text=True).strip()  # noqa: S607
    except Exception:
        return "unknown"


def pytest_runtest_logreport(report):
    if MODULE not in report.nodeid or report.when != "call":
        return
    _results.append({"nodeid": report.nodeid, "outcome": report.outcome,
                     "duration_s": round(report.duration, 3),
                     "error": str(report.longrepr)[-600:] if report.failed else ""})


def pytest_sessionfinish(session, exitstatus):
    out = os.getenv("ENDPOINT_REPORT_DIR")
    if not out or not _results:
        return
    from tests import test_endpoints_post_commit as mod

    endpoints = {"test_budget_summary_reports_the_seeded_period": ("GET", "/api/budgets/summary"),
                 "test_create_budget_then_duplicate_and_invalid_bodies": ("POST", "/api/budgets")}
    tests = []
    for r in _results:
        name = r["nodeid"].split("::")[-1]
        method, path = endpoints.get(name, ("", ""))
        key = f"{method} {path}".strip()
        tests.append({"test": name, "method": method, "endpoint": path, "outcome": r["outcome"],
                      "duration_s": r["duration_s"], "checks": mod.CHECKS.get(key, []), "error": r["error"]})
    passed = sum(1 for t in tests if t["outcome"] == "passed")
    report = {
        "student": "student-4", "name": "Cong Bao Nguyen", "feature": "budgeting",
        "workflow": "student-4-budgets-ci", "job": "endpoint-tests",
        "commit": _git_sha(), "branch": os.getenv("GITHUB_REF_NAME", "local"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "run_url": (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                    if os.getenv("GITHUB_RUN_ID") else ""),
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_url": mod.OBSERVED.get("api_url", ""), "spending_source": mod.OBSERVED.get("spending_source", ""),
        "ai_services": {"mcp": "disabled", "rag": "disabled", "multi_agent": "disabled"},
        "tests": tests,
        "summary": {"endpoints": len(tests), "passed": passed, "failed": len(tests) - passed,
                    "checks": sum(len(t["checks"]) for t in tests), "result": "passed" if passed == len(tests) else "failed"},
    }
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "post-commit-endpoint-report-student-4.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    where = f"run {report['run_id']} on {report['branch']}" if report["run_id"] != "local" else "a local run"
    lines = [
        "# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)", "",
        f"Workflow `student-4-budgets-ci`, job `endpoint-tests`, {where}, commit `{report['commit']}`, {report['ran_at']}.",
        f"Target `{report['api_url']}` with the seeded database; spending source `{report['spending_source']}`;",
        "MCP, RAG and the Multi-Agent Server disabled. Result: **" + report["summary"]["result"] + "**,",
        f"{passed}/{len(tests)} endpoint tests, {report['summary']['checks']} checks.", "",
        "| Endpoint | Test | Outcome | Checks | Seconds |", "|---|---|---|---|---|",
    ]
    for t in tests:
        lines.append(f"| `{t['method']} {t['endpoint']}` | {t['test']} | {t['outcome']} | {len(t['checks'])} | {t['duration_s']} |")
    for t in tests:
        lines += ["", f"## {t['method']} {t['endpoint']}", ""]
        for c in t["checks"]:
            mark = "pass" if c["ok"] else "FAIL"
            detail = f" ({c['detail']})" if c.get("detail") else ""
            lines.append(f"- {mark}: {c['check']}{detail}")
        if t["error"]:
            lines += ["", "```", t["error"], "```"]
    (Path(out) / "post-commit-endpoint-report-student-4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nendpoint report written to {out}/post-commit-endpoint-report-student-4.{{json,md}} ({time.strftime('%H:%M:%S')})")
