"""Writes the post-commit endpoint test report when ENDPOINT_REPORT_DIR is set.

Only the endpoint test module is reported; the other modules in this folder are
plain-runner checks and are not collected by pytest in CI. The report is written
whatever happened, including a run where the API never came up, so a failed run
leaves evidence too.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404  # local git metadata only
from datetime import datetime, timezone
from pathlib import Path

MODULE = "test_endpoints_post_commit"
_results: dict[str, dict] = {}        # nodeid -> outcome of its phases


def _git_sha() -> str:
    """The short id of the commit under test: ENDPOINT_COMMIT when the workflow
    passes the pull request's head (GITHUB_SHA is a merge commit on pull_request
    events), else the checkout. Short, so detect-secrets does not read it as a
    high-entropy string in the report."""
    for name in ("ENDPOINT_COMMIT", "GITHUB_SHA"):
        if os.getenv(name):
            return os.environ[name][:7]
    try:
        return subprocess.check_output(  # noqa: S603  # constant executable, repo-local
            ["git", "rev-parse", "--short=7", "HEAD"], text=True).strip()  # noqa: S607
    except Exception:
        return "unknown"


def pytest_runtest_logreport(report):
    if MODULE not in report.nodeid:
        return
    entry = _results.setdefault(report.nodeid, {"outcome": "not run", "duration_s": 0.0, "error": ""})
    if report.when == "call":
        entry.update(outcome=report.outcome, duration_s=round(report.duration, 3))
        if report.failed:
            entry["error"] = str(report.longrepr)[-600:]
    elif report.failed:                                      # setup (the API never came up) or teardown
        entry.update(outcome="error", error=f"{report.when}: {str(report.longrepr)[-600:]}")
    elif report.when == "setup" and report.skipped:
        entry.update(outcome="skipped", error=str(report.longrepr)[-300:])


def pytest_sessionfinish(session, exitstatus):
    out = os.getenv("ENDPOINT_REPORT_DIR")
    if not out:
        return
    try:
        from tests import test_endpoints_post_commit as mod
        endpoints, checks, observed = mod.ENDPOINTS, mod.CHECKS, mod.OBSERVED
    except Exception as exc:                                # the module itself could not load
        endpoints, checks, observed = {}, {}, {"import_error": f"{type(exc).__name__}: {exc}"}

    tests = []
    for nodeid, r in _results.items():
        name = nodeid.split("::")[-1]
        method, path = endpoints.get(name, ("", ""))
        tests.append({"test": name, "method": method, "endpoint": path, "outcome": r["outcome"],
                      "duration_s": r["duration_s"], "checks": checks.get(name, []), "error": r["error"]})
    passed = sum(1 for t in tests if t["outcome"] == "passed")
    failed = sum(1 for t in tests if t["outcome"] in ("failed", "error", "not run"))
    skipped = sum(1 for t in tests if t["outcome"] == "skipped")
    result = "passed" if tests and failed == 0 and exitstatus == 0 else "failed"
    ai = observed.get("ai_services") or {"mcp": "not observed", "rag": "not observed", "multi_agent": "not observed"}
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    report = {
        "student": "student-4", "name": "Cong Bao Nguyen", "feature": "budgeting",
        "workflow": "student-4-budgets-ci", "job": os.getenv("GITHUB_JOB", "local"),
        "commit": _git_sha(),
        "branch": os.getenv("ENDPOINT_BRANCH") or os.getenv("GITHUB_REF_NAME", "local"),
        "run_id": run_id,
        "run_url": (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
                    if os.getenv("GITHUB_RUN_ID") and os.getenv("GITHUB_REPOSITORY") else ""),
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_url": observed.get("api_url", os.getenv("BUDGET_API_URL", "")),
        "spending_source": observed.get("spending_source", "not observed"),
        "ai_services": ai,
        "pytest_exit_status": int(exitstatus),
        "tests": tests,
        "summary": {"endpoints": len(tests), "passed": passed, "failed": failed, "skipped": skipped,
                    "checks": sum(len(t["checks"]) for t in tests), "result": result},
    }
    if "import_error" in observed:
        report["error"] = observed["import_error"]
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "post-commit-endpoint-report-student-4.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    where = f"run {run_id} on `{report['branch']}`" if run_id != "local" else "a local run"
    flags = ", ".join(f"{k} {v}" for k, v in ai.items())
    lines = [
        "# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)", "",
        f"Workflow `student-4-budgets-ci`, job `{report['job']}`, {where}, commit `{report['commit']}`, {report['ran_at']}.",
        f"Target `{report['api_url']}` with the seeded database; spending source `{report['spending_source']}`;",
        f"AI services as the API reported them: {flags}. Result: **{result}**,",
        f"{passed}/{len(tests)} endpoint tests passed, {report['summary']['checks']} checks"
        + (f", {skipped} skipped" if skipped else "") + ".", "",
        "| Endpoint | Test | Outcome | Checks | Seconds |", "|---|---|---|---|---|",
    ]
    for t in tests:
        lines.append(f"| `{t['method']} {t['endpoint']}`".rstrip() + f" | {t['test']} | {t['outcome']} | {len(t['checks'])} | {t['duration_s']} |")
    if not tests:
        lines += ["", f"No endpoint test ran (pytest exit status {exitstatus}).", ""]
        if report.get("error"):
            lines += ["```", report["error"], "```"]
    for t in tests:
        lines += ["", f"## {t['method']} {t['endpoint']}".rstrip(), ""]
        for c in t["checks"]:
            mark = "note" if c.get("info") else ("pass" if c["ok"] else "FAIL")
            detail = f" ({c['detail']})" if c.get("detail") else ""
            lines.append(f"- {mark}: {c['check']}{detail}")
        if t["error"]:
            lines += ["", "```", t["error"], "```"]
    (Path(out) / "post-commit-endpoint-report-student-4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nendpoint report written to {out}/post-commit-endpoint-report-student-4.{{json,md}}: {result}")
