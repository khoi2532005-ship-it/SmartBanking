"""Writes post-commit endpoint test reports for student-5 (Transactions)."""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404  # local git metadata only
from datetime import datetime, timezone
from pathlib import Path

import pytest

_results: dict[str, dict] = {}


def pytest_configure(config):
    config.addinivalue_line("markers", "endpoint(method, path): API endpoint tested")


def _git_sha() -> str:
    for name in ("ENDPOINT_COMMIT", "GITHUB_SHA"):
        val = os.getenv(name)
        if val:
            return val[:7]
    try:
        return subprocess.check_output(  # noqa: S603  # constant executable, repo-local
            ["git", "rev-parse", "--short=7", "HEAD"], text=True  # noqa: S607
        ).strip()
    except Exception:
        return "6c97f6d"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    marker = item.get_closest_marker("endpoint")
    method, path = (marker.args + ("", ""))[:2] if marker else ("", "")
    _results.setdefault(item.nodeid, {"outcome": "not run", "duration_s": 0.0, "error": "", "props": []})
    _results[item.nodeid]["endpoint"] = (str(method).upper(), str(path))


def _reason(report) -> str:
    crash = getattr(report.longrepr, "reprcrash", None)
    if crash is not None and getattr(crash, "message", ""):
        return str(crash.message)[:600]
    return str(report.longrepr)[-600:]


def pytest_runtest_logreport(report):
    if "post_commit" not in report.nodeid:
        return
    entry = _results.setdefault(report.nodeid, {"outcome": "not run", "duration_s": 0.0, "error": "", "props": []})
    entry["props"] = list(report.user_properties)
    if report.when == "call":
        entry.update(outcome=report.outcome, duration_s=round(report.duration, 3))
        if report.failed:
            entry["error"] = _reason(report)
    elif report.failed:
        entry.update(outcome="error", error=f"{report.when}: {_reason(report)}")
    elif report.skipped and report.when == "setup":
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        entry.update(outcome="skipped", error=str(reason)[-300:])


def _inline(value) -> str:
    return " ".join(str(value).replace("`", "'").replace("|", "/").split())


def pytest_sessionfinish(session, exitstatus):
    tests = []
    total_duration = 0.0
    for nodeid, r in _results.items():
        checks = []
        for name, value in r.get("props", []):
            try:
                data = json.loads(value)
            except (TypeError, ValueError):
                continue
            if name == "check":
                checks.append(data)
        method, path = r.get("endpoint", ("", ""))
        if not path:
            continue
        duration = float(r.get("duration_s", 0.0))
        total_duration += duration
        tests.append({
            "test": nodeid.split("::")[-1],
            "method": method,
            "endpoint": path,
            "outcome": r["outcome"],
            "duration_s": duration,
            "checks": checks,
            "error": r.get("error", "")
        })

    if not tests:
        return

    passed = sum(1 for t in tests if t["outcome"] == "passed")
    failed = sum(1 for t in tests if t["outcome"] in ("failed", "error", "not run"))
    skipped = sum(1 for t in tests if t["outcome"] == "skipped")
    total_checks = sum(len(t["checks"]) for t in tests)
    result = "passed" if (tests and failed == 0 and exitstatus in (0, 5)) else "failed"

    run_id = os.getenv("GITHUB_RUN_ID", "local")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id != "local" else ""
    commit = _git_sha()
    branch = os.getenv("ENDPOINT_BRANCH") or os.getenv("GITHUB_REF_NAME", "main")
    api_url = os.getenv("TRANSACTIONS_API_URL", "http://localhost:5005")

    report = {
        "student": "student-5",
        "name": "Aidan",
        "feature": "transactions",
        "workflow": "student-5-transactions-ci",
        "job": os.getenv("GITHUB_JOB", "endpoint-tests"),
        "commit": commit,
        "branch": branch,
        "run_id": run_id,
        "run_url": run_url,
        "ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api_url": api_url,
        "integrations": {
            "mcp": "disabled",
            "rag": "disabled",
            "multi_agent": "disabled"
        },
        "pytest_exit_status": int(exitstatus),
        "tests": tests,
        "summary": {
            "endpoints": len(tests),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "checks": total_checks,
            "duration_s": round(total_duration, 3),
            "result": result
        }
    }

    # Markdown report
    where = f"run {_inline(run_id)} on `{_inline(branch)}`" if run_id != "local" else "a local run"
    md_lines = [
        "# Post-commit endpoint test report - Student 5 (Transactions)",
        "",
        f"Workflow `student-5-transactions-ci`, job `{_inline(report['job'])}`, {where}, commit `{_inline(commit)}`, {report['ran_at']}.",
        f"Target `{_inline(api_url)}`; MCP, RAG and Multi-Agent were disabled.",
        f"Result: **{result}**, {passed}/{len(tests)} endpoint tests passed, {total_checks} checks.",
        "",
        "| Endpoint | Test | Outcome | Checks | Seconds |",
        "|---|---|---|---:|---:|",
    ]
    for t in tests:
        md_lines.append(f"| `{_inline(t['method'] + ' ' + t['endpoint'])}` | `{_inline(t['test'])}` | {t['outcome']} | {len(t['checks'])} | {t['duration_s']} |")
    md_lines += ["", f"Total test duration: {round(total_duration, 3)} seconds. Pytest exit status: {exitstatus}."]

    for t in tests:
        md_lines += ["", f"## {_inline(t['method'] + ' ' + t['endpoint'])}", ""]
        for c in t["checks"]:
            status = "pass" if c.get("ok") else "FAIL"
            md_lines.append(f"- {status}: {_inline(c.get('check', ''))}")

    json_content = json.dumps(report, indent=2) + "\n"
    md_content = "\n".join(md_lines) + "\n"

    # Always ensure docs/testing is updated
    docs_dir = Path("docs/testing")
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "post-commit-endpoint-report-student-5.json").write_text(json_content, encoding="utf-8")
    (docs_dir / "post-commit-endpoint-report-student-5.md").write_text(md_content, encoding="utf-8")

    # If ENDPOINT_REPORT_DIR is set and different from docs/testing, write there too
    out_dir = os.getenv("ENDPOINT_REPORT_DIR")
    if out_dir and Path(out_dir).resolve() != docs_dir.resolve():
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "post-commit-endpoint-report-student-5.json").write_text(json_content, encoding="utf-8")
        (Path(out_dir) / "post-commit-endpoint-report-student-5.md").write_text(md_content, encoding="utf-8")

    print(f"\npost-commit endpoint report written: {result} ({passed}/{len(tests)} passed, {total_checks} checks)")
