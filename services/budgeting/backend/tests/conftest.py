"""Writes the post-commit endpoint test report when ENDPOINT_REPORT_DIR is set.

Everything comes from pytest itself: each test's endpoint from its `endpoint` marker,
its checks and observations from the properties it recorded (record_property), and its
outcome from the setup, call and teardown reports. Nothing re-imports the test module,
so the report is the same whatever the import mode. It is written whatever the outcome,
including a run where the API never came up or every test skipped.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404  # local git metadata only
from datetime import datetime, timezone
from pathlib import Path

import pytest

MODULE = "test_endpoints_post_commit"
_results: dict[str, dict] = {}        # nodeid -> outcome, endpoint, recorded properties


def pytest_configure(config):
    config.addinivalue_line("markers", "endpoint(method, path): the API endpoint function a test covers")


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


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if MODULE in item.nodeid:
        marker = item.get_closest_marker("endpoint")
        method, path = (marker.args + ("", ""))[:2] if marker else ("", "")
        _results.setdefault(item.nodeid, {"outcome": "not run", "duration_s": 0.0, "error": "", "props": []})
        _results[item.nodeid]["endpoint"] = (str(method).upper(), str(path))


def _reason(report) -> str:
    """The failure's own message (the assertion or pytest.fail text), else the traceback's tail."""
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None and getattr(crash, "message", ""):
        return str(crash.message)[:600]
    return str(report.longrepr)[-600:]


def pytest_runtest_logreport(report):
    if MODULE not in report.nodeid:
        return
    entry = _results.setdefault(report.nodeid, {"outcome": "not run", "duration_s": 0.0, "error": "", "props": []})
    entry["props"] = list(report.user_properties)          # cumulative across phases; the last one has them all
    if report.when == "call":
        entry.update(outcome=report.outcome, duration_s=round(report.duration, 3))
        if report.failed:
            entry["error"] = _reason(report)
    elif report.failed:                                    # setup (the API never came up) or teardown
        entry.update(outcome="error", error=f"{report.when}: {_reason(report)}")
    elif report.skipped and report.when == "setup":
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        entry.update(outcome="skipped", error=str(reason)[-300:])


def _inline(value) -> str:
    """A value that is safe inside Markdown inline code or a table cell."""
    return " ".join(str(value).replace("`", "'").replace("|", "/").split())


def _block(text: str) -> list[str]:
    """Text as an indented code block, which no backtick run inside it can break."""
    return [""] + ["    " + line for line in str(text).splitlines()] + [""]


def pytest_sessionfinish(session, exitstatus):
    out = os.getenv("ENDPOINT_REPORT_DIR")
    if not out:
        return
    tests, observed = [], {}
    for nodeid, r in _results.items():
        checks = []
        for name, value in r.get("props", []):
            try:
                data = json.loads(value)
            except (TypeError, ValueError):
                continue
            if name == "check":
                checks.append(data)
            elif name == "observed":
                observed.update(data)
        method, path = r.get("endpoint", ("", ""))
        tests.append({"test": nodeid.split("::")[-1], "method": method, "endpoint": path, "outcome": r["outcome"],
                      "duration_s": r["duration_s"], "checks": checks, "error": r["error"]})
    passed = sum(1 for t in tests if t["outcome"] == "passed")
    failed = sum(1 for t in tests if t["outcome"] in ("failed", "error", "not run"))
    skipped = sum(1 for t in tests if t["outcome"] == "skipped")
    if not tests or failed or exitstatus not in (0, 5):
        result = "failed"
    elif passed == 0:
        result = "skipped"
    else:
        result = "passed"
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
        "api_url": observed.get("api_url") or os.getenv("BUDGET_API_URL", "http://localhost:5004"),
        "spending_source": observed.get("spending_source", "not observed"),
        "ai_services": ai,
        "pytest_exit_status": int(exitstatus),
        "tests": tests,
        "summary": {"endpoints": len(tests), "passed": passed, "failed": failed, "skipped": skipped,
                    "checks": sum(len(t["checks"]) for t in tests), "result": result},
    }
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "post-commit-endpoint-report-student-4.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    where = f"run {_inline(run_id)} on `{_inline(report['branch'])}`" if run_id != "local" else "a local run"
    flags = ", ".join(f"{k} {v}" for k, v in ai.items())
    lines = [
        "# Post-commit endpoint test report - Student 4 (Budgeting & Spending Insights)", "",
        f"Workflow `student-4-budgets-ci`, job `{_inline(report['job'])}`, {where}, commit `{_inline(report['commit'])}`, {report['ran_at']}.",
        f"Target `{_inline(report['api_url'])}` with the seeded database; spending source `{_inline(report['spending_source'])}`;",
        f"AI services as the API reported them: {_inline(flags)}. Result: **{result}**,",
        f"{passed}/{len(tests)} endpoint tests passed, {report['summary']['checks']} checks"
        + (f", {skipped} skipped" if skipped else "") + ".", "",
        "| Endpoint | Test | Outcome | Checks | Seconds |", "|---|---|---|---|---|",
    ]
    for t in tests:
        lines.append(f"| `{_inline(t['method'] + ' ' + t['endpoint'])}` | {_inline(t['test'])} | {t['outcome']} | {len(t['checks'])} | {t['duration_s']} |")
    if not tests:
        lines += ["", f"No endpoint test ran (pytest exit status {exitstatus})."]
    for t in tests:
        lines += ["", f"## {_inline(t['method'] + ' ' + t['endpoint'])}", ""]
        for c in t["checks"]:
            mark = "note" if c.get("info") else ("pass" if c.get("ok") else "FAIL")
            detail = f" ({_inline(c['detail'])})" if c.get("detail") else ""
            lines.append(f"- {mark}: {_inline(c.get('check', ''))}{detail}")
        if t["error"]:
            lines += _block(t["error"])
    (Path(out) / "post-commit-endpoint-report-student-4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nendpoint report written to {out}/post-commit-endpoint-report-student-4.{{json,md}}: {result}")
