"""Testing Report Review mode - Bao (Release 2).

Reviews the team's testing evidence: each student's pre-commit security report
and post-commit CI/CD endpoint test report, and has the model write the
Testing Review entry.

ACT reads the report files, one naming convention for the whole team:

    docs/testing/pre-commit-security-report-student-<N>.json
    docs/testing/post-commit-endpoint-report-student-<N>.json
    docs/release-2/ci/student-<N>/*.xml      (JUnit results, when a student kept those instead)

OBSERVE rejects an entry that invents a scan or a student, misquotes a scan's
findings, fixes or accepted count, a test outcome, an endpoint count or the
coverage, or calls ATTENTION a PASS; ADAPT retries with that complaint. With
no report in reach the run stops before any token is spent. A report that
cannot be parsed is counted as missing and the run is marked degraded.

Env: TESTING_REPORTS_DIR (default docs/testing), CI_EVIDENCE_DIR (default docs/release-2/ci).
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET  # noqa: S405  # the team's own JUnit files, not untrusted input
from collections import Counter
from pathlib import Path
from typing import Any

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict
from agentic.modes._review_common import DOCS_DIR, line_for, read_json, rel

PROMPT_FAMILY = "_testing_review"
STUDENTS = {1: "accounts", 2: "loans", 3: "fraud-alerts", 4: "budgeting", 5: "transactions"}
REQUIRED_LINES = ("pre-commit", "post-commit", "coverage", "recommendation", "verdict")
COUNTS_RE = re.compile(r"(?<![\d/])(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s+(passed|failed)\b")   # any scan's figures
# "<METHOD> <path> <passed>/<tests> passed", or for an endpoint with one test, "<METHOD> <path> <outcome>"
ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,;:]+)\s*:?\s*(?:(\d+)\s*/\s*(\d+)\s+)?"
                         r"(passed|failed|error|skipped)\b", re.I)
JUNIT_RE = re.compile(r"(\d+)\s+tests?\s+(\d+)\s+failures?\s+(\d+)\s+errors?")
STUDENT_RE = re.compile(r"student-(\d)\b")
COVERAGE_RE = re.compile(r"(?<!\d)(\d+)\s+of\s+(\d+)(?!\d)")


def _scan_re(name: str) -> re.Pattern[str]:
    """A scan's name, spelled any way the report spells it (spaces, capitals), then its figures."""
    words = r"\s+".join(re.escape(word) for word in name.split())
    return re.compile(rf"(?<![\w-]){words}\s*:?\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s+(passed|failed)\b")


def _label_before(text: str, pos: int) -> str:
    """The words in front of a figure, back to the previous comma or semicolon: the name the entry gave it."""
    start = max(text.rfind(",", 0, pos), text.rfind(";", 0, pos)) + 1
    return " ".join(text[start:pos].split()) or "an unnamed scan"


def _endpoints(tests: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The report's tests grouped by endpoint, in the order the report first names each one."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for t in tests:
        group = groups.setdefault((t["method"], t["endpoint"].lower()),
                                  {"method": t["method"], "endpoint": t["endpoint"], "outcomes": []})
        group["outcomes"].append(t["outcome"])
    for group in groups.values():
        group["tests"] = len(group["outcomes"])
        group["passed"] = group["outcomes"].count("passed")
        group["text"] = f"{group['method']} {group['endpoint']} {group['passed']}/{group['tests']} passed"
    return list(groups.values())


def reports_dir() -> Path:
    return Path(os.getenv("TESTING_REPORTS_DIR") or (DOCS_DIR / "testing"))


def ci_dir() -> Path:
    return Path(os.getenv("CI_EVIDENCE_DIR") or (DOCS_DIR / "release-2" / "ci"))


def _count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _pre_commit(path: Path) -> dict[str, Any] | None:
    data = read_json(path)
    if not data or not isinstance(data.get("scans"), list):
        return None
    scans = []
    for scan in data["scans"]:
        if not isinstance(scan, dict) or not scan.get("name"):
            continue
        scans.append({"name": " ".join(str(scan["name"]).lower().split()), "result": str(scan.get("result", "")).lower(),
                      "findings": _count(scan.get("findings")), "fixed": _count(scan.get("fixed")),
                      "accepted": _count(scan.get("accepted"))})
    if not scans:
        return None
    result = str((data.get("summary") or {}).get("result") or ("passed" if all(s["result"] == "passed" for s in scans) else "failed")).lower()
    return {"file": rel(path), "commit": str(data.get("commit", "")), "scans": scans, "result": result}


def _post_commit_json(path: Path) -> dict[str, Any] | None:
    data = read_json(path)
    if not data or not isinstance(data.get("tests"), list):
        return None
    tests = [{"method": str(t.get("method", "")).upper(), "endpoint": str(t.get("endpoint", "")),
              "outcome": str(t.get("outcome", "")).lower()}
             for t in data["tests"] if isinstance(t, dict) and t.get("endpoint")]
    summary = data.get("summary") or {}
    passed = int(summary.get("passed", sum(1 for t in tests if t["outcome"] == "passed")))
    # One report may test an endpoint many times (fraud has 17 tests of GET /api/alerts):
    # the entry names each endpoint once, with its passed and total tests.
    endpoints = _endpoints(tests)
    return {"file": rel(path), "source": "json", "commit": str(data.get("commit", "")), "run_id": str(data.get("run_id", "")),
            "tests": tests, "endpoint_groups": endpoints, "endpoints": len(endpoints), "test_count": len(tests),
            "passed": passed, "checks": int(summary.get("checks", 0) or 0),
            "result": str(summary.get("result") or ("passed" if tests and passed == len(tests) else "failed")).lower()}


def _post_commit_junit(folder: Path) -> dict[str, Any] | None:
    files = sorted(folder.glob("*.xml")) if folder.is_dir() else []
    tests = failures = errors = 0
    used = []
    for path in files:
        try:
            root = ET.parse(path).getroot()  # noqa: S314  # the team's own CI artifact
        except (ET.ParseError, OSError):
            continue
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            tests += int(suite.get("tests", 0) or 0)
            failures += int(suite.get("failures", 0) or 0)
            errors += int(suite.get("errors", 0) or 0)
        used.append(rel(path))
    if not used or tests == 0:
        return None
    return {"file": ", ".join(used), "source": "junit", "tests": tests, "failures": failures, "errors": errors,
            "result": "passed" if failures == 0 and errors == 0 else "failed"}


class TestingReviewMode(Mode):
    key = "testing_review"
    label = "Testing Report Review"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=("Review every student's pre-commit security report and post-commit endpoint test report "
                  "and write the Testing Review entry from their figures"),
            checks=[
                f"the reports under {rel(reports_dir())} follow the team naming convention (student-1 to student-5)",
                "each pre-commit report names its scans with findings, fixed and accepted counts and a result",
                "each post-commit report names the endpoints tested, their outcomes and the check count (or JUnit totals)",
                "the entry quotes every scan name, count, outcome and the coverage exactly as the reports say",
                "a failed report or a student without a report makes the verdict ATTENTION, never PASS",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        folder = reports_dir()
        students = []
        unreadable = []
        for n, feature in STUDENTS.items():
            pre_path = folder / f"pre-commit-security-report-student-{n}.json"
            post_path = folder / f"post-commit-endpoint-report-student-{n}.json"
            pre = _pre_commit(pre_path) if pre_path.is_file() else None
            if pre_path.is_file() and pre is None:
                unreadable.append(rel(pre_path))
            post = _post_commit_json(post_path) if post_path.is_file() else None
            if post_path.is_file() and post is None:
                unreadable.append(rel(post_path))
            if post is None:
                post = _post_commit_junit(ci_dir() / f"student-{n}")
            students.append({"student": f"student-{n}", "feature": feature, "pre_commit": pre, "post_commit": post})
        with_pre = [s["student"] for s in students if s["pre_commit"]]
        with_post = [s["student"] for s in students if s["post_commit"]]
        if not with_pre and not with_post:
            return Evidence(ok=False, summary=(
                f"no testing report found under {rel(folder)} (expected pre-commit-security-report-student-<N>.json "
                f"and post-commit-endpoint-report-student-<N>.json) or JUnit files under {rel(ci_dir())}"))
        missing = [s["student"] for s in students if not (s["pre_commit"] and s["post_commit"])]
        failed = [s["student"] for s in students
                  if (s["pre_commit"] and s["pre_commit"]["result"] != "passed")
                  or (s["post_commit"] and s["post_commit"]["result"] != "passed")]
        attention = bool(missing or failed)
        facts = {"reports_dir": rel(folder), "students": students, "with_pre_commit": with_pre,
                 "with_post_commit": with_post, "missing": missing, "failed": failed, "unreadable": unreadable,
                 "attention": attention, "student_count": len(STUDENTS)}
        pre_text = "; ".join(
            f"{s['student']} " + ", ".join(f"{sc['name']} {sc['findings']}/{sc['fixed']}/{sc['accepted']} {sc['result']}"
                                           for sc in s["pre_commit"]["scans"])
            for s in students if s["pre_commit"]) or "none"
        post_text = "; ".join(
            f"{s['student']} " + (
                ", ".join(g["text"] for g in s["post_commit"]["endpoint_groups"])
                + f" ({s['post_commit']['endpoints']} endpoints, {s['post_commit']['passed']}/{s['post_commit']['test_count']} tests,"
                  f" {s['post_commit']['checks']} checks)"
                if s["post_commit"]["source"] == "json" else
                f"{s['post_commit']['tests']} tests {s['post_commit']['failures']} failures {s['post_commit']['errors']} errors (junit)")
            for s in students if s["post_commit"]) or "none"
        no_pre = [s["student"] for s in students if not s["pre_commit"]]
        no_post = [s["student"] for s in students if not s["post_commit"]]
        return Evidence(
            ok=True,
            summary=(f"Pre-commit reports: {pre_text}; no pre-commit report: {', '.join(no_pre) or 'none'}. "
                     f"Post-commit reports: {post_text}; no post-commit report: {', '.join(no_post) or 'none'}. "
                     f"Coverage {len(with_pre)} of {len(STUDENTS)} pre-commit, {len(with_post)} of {len(STUDENTS)} post-commit; "
                     f"missing one or both: {', '.join(missing) if missing else 'none'}; failed: {', '.join(failed) if failed else 'none'}"),
            facts=facts,
            degraded=bool(unreadable),
            note=("could not parse: " + ", ".join(unreadable) + "; those count as missing") if unreadable else "",
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(PROMPT_FAMILY, "review_system.txt", "review_task.txt")
        f = evidence.facts
        lines = [f"Reports folder: {f['reports_dir']}", "Students:"]
        for s in f["students"]:
            pre = s["pre_commit"]
            post = s["post_commit"]
            pre_text = ("; ".join(f"{sc['name']} findings {sc['findings']}, fixed {sc['fixed']}, accepted {sc['accepted']}, {sc['result']}"
                                  for sc in pre["scans"]) + f" (commit {pre['commit']}, {pre['file']})") if pre else "no pre-commit report"
            if post and post["source"] == "json":
                post_text = (", ".join(g["text"] for g in post["endpoint_groups"])
                             + f"; {post['endpoints']} endpoints, {post['passed']}/{post['test_count']} tests passed,"
                               f" {post['checks']} checks, result {post['result']}"
                             + f" (commit {post['commit']}, run {post['run_id']}, {post['file']})")
            elif post:
                post_text = (f"JUnit: {post['tests']} tests, {post['failures']} failures, {post['errors']} errors, "
                             f"result {post['result']} ({post['file']})")
            else:
                post_text = "no post-commit report"
            lines.append(f"- {s['student']} ({s['feature']}): pre-commit: {pre_text}. post-commit: {post_text}.")
        lines += [
            f"Coverage: {len(f['with_pre_commit'])} of {f['student_count']} students have a pre-commit report "
            f"({', '.join(f['with_pre_commit']) or 'none'}); {len(f['with_post_commit'])} of {f['student_count']} have a "
            f"post-commit report ({', '.join(f['with_post_commit']) or 'none'}); missing one or both: "
            f"{', '.join(f['missing']) if f['missing'] else 'none'}",
            f"Failed reports: {', '.join(f['failed']) if f['failed'] else 'none'}",
            f"Required verdict word: {'ATTENTION' if f['attention'] else 'PASS'}",
        ]
        correction = ""
        if feedback:
            correction = (f"\n\nYour previous entry was rejected: {feedback}. Fix exactly that. Keep the five-line "
                          "format and copy scan names, counts, endpoints and outcomes from the evidence verbatim.")
        return system_prompt, f"{task_prompt}{correction}\n\nEvidence:\n" + "\n".join(lines)

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        f = evidence.facts
        reasons: list[str] = []
        if not output.strip():
            return Verdict(False, ["the entry was empty"])
        lines = {label: line_for(output, label) for label in REQUIRED_LINES}
        for label, line in lines.items():
            if not line:
                reasons.append(f"it did not include the '{label.capitalize()}:' line")

        known = {s["student"] for s in f["students"]}
        for n in set(STUDENT_RE.findall(output)):
            if f"student-{n}" not in known:
                reasons.append(f"it named student-{n}, who is not in the evidence; use only student-1 to student-{f['student_count']}")

        def segments(line: str) -> dict[str, str]:
            parts = re.split(r"\b(student-\d)\b", line)
            return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}

        pre_line = lines["pre-commit"].lower()
        if pre_line:
            segs = segments(pre_line)
            for s in f["students"]:
                pre = s["pre_commit"]
                seg = segs.get(s["student"], "")
                if pre is None:
                    if seg and "none" not in seg and COUNTS_RE.search(seg):
                        reasons.append(f"the Pre-commit line reports scans for {s['student']}, who has no pre-commit report")
                    continue
                if not seg:
                    reasons.append(f"the Pre-commit line did not report {s['student']}")
                    continue
                quoted_spans = []
                for scan in pre["scans"]:
                    expected = (str(scan["findings"]), str(scan["fixed"]), str(scan["accepted"]), scan["result"])
                    match = _scan_re(scan["name"]).search(seg)
                    if not match:
                        reasons.append(f"the Pre-commit line must state for {s['student']}: {scan['name']} "
                                       f"{scan['findings']}/{scan['fixed']}/{scan['accepted']} {scan['result']}")
                        continue
                    quoted_spans.append(match.span())
                    if match.groups() != expected:
                        reasons.append(f"the Pre-commit line misquotes {s['student']} {scan['name']}: the report says "
                                       f"{scan['findings']}/{scan['fixed']}/{scan['accepted']} {scan['result']}")
                # Figures that belong to none of the report's scans name a scan the student did not run.
                invented = [_label_before(seg, m.start()) for m in COUNTS_RE.finditer(seg)
                            if not any(start <= m.start() < end for start, end in quoted_spans)]
                if invented:
                    reasons.append(f"the Pre-commit line names scan(s) {s['student']} did not run: " + ", ".join(invented))

        post_line = lines["post-commit"]
        if post_line:
            segs = segments(post_line.lower())
            for s in f["students"]:
                post = s["post_commit"]
                seg = segs.get(s["student"], "")
                if post is None:
                    if seg and "none" not in seg and (ENDPOINT_RE.search(seg) or JUNIT_RE.search(seg)):
                        reasons.append(f"the Post-commit line reports tests for {s['student']}, who has no post-commit report")
                    continue
                if not seg:
                    reasons.append(f"the Post-commit line did not report {s['student']}")
                    continue
                if post["source"] == "json":
                    groups = {(g["method"], g["endpoint"].lower()): g for g in post["endpoint_groups"]}
                    quoted: dict[tuple[str, str], list[tuple[str | None, str | None, str]]] = {}
                    for m in ENDPOINT_RE.finditer(seg):
                        quoted.setdefault((m.group(1).upper(), m.group(2).lower()), []).append(
                            (m.group(3), m.group(4), m.group(5).lower()))
                    for key, g in groups.items():
                        got = quoted.get(key, [])
                        if not got:
                            reasons.append(f"the Post-commit line must state for {s['student']}: {g['text']}")
                            continue

                        def faithful(passed: str | None, total: str | None, word: str, g: dict[str, Any] = g) -> bool:
                            if passed is not None:
                                return (int(passed), int(total), word) == (g["passed"], g["tests"], "passed")
                            return g["tests"] == 1 and word == g["outcomes"][0]      # one test: its outcome will do
                        if not all(faithful(*q) for q in got):
                            reasons.append(f"the Post-commit line misquotes {s['student']} {g['method']} {g['endpoint']}: "
                                           f"the report says {g['passed']}/{g['tests']} passed")
                    for key in sorted(set(quoted) - set(groups)):
                        reasons.append(f"the Post-commit line names {key[0]} {key[1]} for {s['student']}, "
                                       "which that report does not test")
                    match = re.search(r"(?<![\d/])(\d+)\s+endpoints?\b", seg)
                    if not match or int(match.group(1)) != post["endpoints"]:
                        reasons.append(f"the Post-commit line must state for {s['student']}: {post['endpoints']} endpoints")
                    match = re.search(r"(?<![\d/])(\d+)\s*/\s*(\d+)\s+tests\b", seg)
                    if not match or (int(match.group(1)), int(match.group(2))) != (post["passed"], post["test_count"]):
                        reasons.append(f"the Post-commit line must state for {s['student']}: "
                                       f"{post['passed']}/{post['test_count']} tests")
                    if not re.search(rf"(?<![\d/]){post['checks']}\s+checks", seg):
                        reasons.append(f"the Post-commit line must state for {s['student']}: {post['checks']} checks")
                else:
                    match = JUNIT_RE.search(seg)
                    expected = (str(post["tests"]), str(post["failures"]), str(post["errors"]))
                    if not match or match.groups() != expected:
                        reasons.append(f"the Post-commit line must state for {s['student']}: {post['tests']} tests "
                                       f"{post['failures']} failures {post['errors']} errors (junit)")

        coverage = lines["coverage"].lower()
        if coverage:
            # Each count is read from its own clause, so one report type's figure never answers for the other.
            clauses = re.split(r"[;,]|\band\b", coverage)
            for count, word in ((len(f["with_pre_commit"]), "pre-commit"), (len(f["with_post_commit"]), "post-commit")):
                stated = [COVERAGE_RE.findall(c) for c in clauses if re.search(rf"(?<![\w-]){word}\b", c)]
                if not any(pairs == [(str(count), str(f["student_count"]))] for pairs in stated):
                    reasons.append(f"the Coverage line must state {count} of {f['student_count']} students for {word}")
            if f["missing"]:
                for student in f["missing"]:
                    if student not in coverage:
                        reasons.append(f"the Coverage line must list {student} as missing a report")
            elif "missing: none" not in coverage:
                reasons.append("the Coverage line must end with 'missing: none'")

        verdict_line = lines["verdict"].lower()
        if verdict_line:
            expected_word = "attention" if f["attention"] else "pass"
            words = re.findall(r"\b(pass|attention)\b", verdict_line)
            if not words or words[0] != expected_word:
                why = (f"missing reports for {', '.join(f['missing'])}" if f["missing"] else "") \
                    + (f"; failed reports for {', '.join(f['failed'])}" if f["failed"] else "")
                reasons.append(f"the Verdict line must start with {expected_word.upper()}"
                               + (f": {why.strip('; ')}" if why else ": every student has both reports and all passed"))

        recommendation = lines["recommendation"]
        if recommendation and len(recommendation.split(":", 1)[-1].strip()) < 20:
            reasons.append("the Recommendation line must say what the team should do next, in at least one full sentence")

        return Verdict(ok=not reasons, reasons=reasons)
