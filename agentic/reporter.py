"""Console output and the evidence log.

Two audiences. The console output is for the showcase demo - each stage is
labelled so a marker watching the terminal can see Plan -> Act -> Observe ->
Adapt actually happening. The written log is for the technical report, which
has to carry pre-testing and post-testing evidence per the project spec.

Every run appends a row to `docs/evidence/evidence-log.md` (paste-ready for
the report) and drops the full transcript in `docs/evidence/<mode>-<ts>.json`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agentic.core import Result

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"

_RULE = "=" * 72


def header(title: str, provider: str) -> None:
    print()
    print(_RULE)
    print(f"  {title}")
    print(f"  model: {provider}")
    print(_RULE)


def stage(mode_label: str, name: str, message: str) -> None:
    """One Plan/Act/Observe/Adapt line. Keep these visible - they are the demo."""
    print(f"  [{mode_label}] {name:<8} {message}")


def result(res: Result) -> None:
    print()
    print(f"  --- {res.mode} result " + "-" * (52 - len(res.mode)))

    if not res.evidence.ok:
        print(f"  OBSERVE FAILED: {res.evidence.summary}")
        print(f"  Nothing was sent to the model. Fix the above and re-run.")
        return

    print(f"  Evidence: {res.evidence.summary}")
    if res.evidence.degraded:
        print(f"  DEGRADED: {res.evidence.note}")

    for attempt in res.attempts:
        print()
        if attempt.adapt_note:
            print(f"  ADAPT -> retry {attempt.n}: {attempt.adapt_note}")
        if attempt.error:
            print(f"  Attempt {attempt.n}: {attempt.error}")
            continue
        print(f"  Attempt {attempt.n} output:")
        for line in attempt.output.splitlines():
            print(f"    {line}")
        verdict = "PASS" if attempt.verdict.ok else f"FAIL - {attempt.verdict.feedback}"
        print(f"  OBSERVE: {verdict}")

    if res.review.ran:
        print()
        print(f"  REVIEW ({res.review.model or 'unavailable'}):")
        for line in (res.review.text or res.review.error).splitlines():
            print(f"    {line}")

    print()
    print(f"  RESULT: {'PASS' if res.ok else 'FAIL'}"
          f"{' (self-corrected on retry)' if res.adapted and res.ok else ''}")


def summary(results: list[Result]) -> None:
    """Printed after 'Run all' so the showcase has one table to point at."""
    print()
    print(_RULE)
    print("  SUMMARY")
    print(_RULE)
    print(f"  {'Feature':<16}{'Evidence':<12}{'Result':<10}{'Attempts'}")
    for res in results:
        evidence = "FAIL" if not res.evidence.ok else ("degraded" if res.evidence.degraded else "ok")
        print(f"  {res.mode:<16}{evidence:<12}{'PASS' if res.ok else 'FAIL':<10}{len(res.attempts)}")
    print()


def write_evidence(res: Result) -> Path:
    """Persist one run. Returns the JSON path so the caller can print it."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    payload = {
        "mode": res.mode,
        "timestamp": stamp,
        "plan": {
            "goal": res.plan.goal,
            "checks": res.plan.checks,
            "stop_condition": res.plan.stop_condition,
        },
        "evidence": {
            "ok": res.evidence.ok,
            "summary": res.evidence.summary,
            "degraded": res.evidence.degraded,
            "note": res.evidence.note,
            "facts": res.evidence.facts,
        },
        "attempts": [
            {
                "n": a.n,
                "adapt_note": a.adapt_note,
                "output": a.output,
                "passed": a.verdict.ok,
                "reasons": a.verdict.reasons,
                "error": a.error,
            }
            for a in res.attempts
        ],
        "review": {
            "model": res.review.model,
            "text": res.review.text,
            "error": res.review.error,
        },
        "passed": res.ok,
        "adapted": res.adapted,
    }

    json_path = EVIDENCE_DIR / f"{res.mode}-{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _append_log_row(res, stamp)
    return json_path


def _append_log_row(res: Result, stamp: str) -> None:
    """Append to the markdown table the technical report needs."""
    log = EVIDENCE_DIR / "evidence-log.md"
    if not log.exists():
        log.write_text(
            "# Agentic Loop Evidence Log\n\n"
            "Appended automatically by `python agentic_loop.py`. "
            "One row per run - paste into the release technical report.\n\n"
            "| Run (UTC) | Feature | Evidence | Attempts | Adapt fired | Result |\n"
            "|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )

    evidence = "FAIL" if not res.evidence.ok else ("degraded" if res.evidence.degraded else "ok")
    row = (
        f"| {stamp} | {res.mode} | {evidence} | {len(res.attempts)} | "
        f"{'yes' if res.adapted else 'no'} | {'PASS' if res.ok else 'FAIL'} |\n"
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write(row)
