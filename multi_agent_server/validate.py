"""Terminal validation of the shared Multi-Agent Server - the Release 2 test record.

    python -m multi_agent_server.validate                 # print the test record
    python -m multi_agent_server.validate --evidence      # also snapshot the run into docs/evidence
    python -m multi_agent_server.validate --url http://localhost:8300

Mirrors mcp_server.validate: each check is call + expected + observed + result.
Pass rule: the server behaves as Lecture 10 describes - bounded stages with
handoff contracts, one revision cycle, a human gate, and two audit files.

    1  reachable            /health answers with the four-stage pipeline
    2  full workflow        Planner -> Worker -> Reviewer -> awaiting_human_review
    3  gate holds           /response is 409 until a person decides
    4  accept releases      the decision releases the Worker's answer
    5  reject recorded      a second workflow is rejected with a note, nothing released
    6  audit files          both JSONL files hold every stage, handoff and decision
    7  contracts            off-contract plan, result and review are rejected with reasons
    8  dependency down      a feature API that is off yields a structured error, not a result
    9  metrics              coordination metrics are computed from the audit files

Checks 1-6 and 9 run against the server at --url. Check 7 is deterministic
code. Check 8 runs the same server code in-process against an unreachable
feature URL, so it never depends on which services happen to be running.

Exit code 0 when every check passes, 1 otherwise, so it can gate a script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from multi_agent_server import config, contracts, terminal
from multi_agent_server.models import State

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
EVIDENCE_AUDIT_DIR = EVIDENCE_DIR / "multi_agent"

CONTEXT = {"customer_id": 1, "month": 9, "year": 2026}
REQUEST_ACCEPT = "Which budget categories went over the limit in September 2026 and by how much?"
REQUEST_REJECT = "What did I spend most on in September 2026, and is my overall budget on track?"
REJECT_NOTE = "Validation run: rejected on purpose to record the withheld path."
UNREACHABLE_URL = "http://127.0.0.1:9"


@dataclass
class Record:
    n: int
    check: str
    call: str
    arguments: dict[str, Any]
    expected: str
    observed: str = ""
    passed: bool = False
    skipped: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _wait_for_gate(client: Any, workflow_id: str, timeout: float, poll: float,
                   sleep=time.sleep) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status, body = client.get(f"/workflow/{workflow_id}/status")
        if status != 200:
            return {"state": "unknown", "error": f"status {status}: {body.get('error')}", "stages": []}
        if body["state"] in (State.AWAITING_HUMAN_REVIEW, *State.TERMINAL):
            return body
        if time.monotonic() > deadline:
            body["error"] = f"still {body['state']} after {timeout:g}s"
            return body
        sleep(poll)


def _stage_summary(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "stages": [f"{s['role']}#{s['attempt']} {s['status']}{' fallback' if s['fallback'] else ''}"
                   + (f" {s['duration_seconds']}s" if s["duration_seconds"] is not None else "")
                   for s in body.get("stages", [])],
        "fallbacks": [s["role"] for s in body.get("stages", []) if s["fallback"]],
        "revisions": body.get("revisions"),
    }


def run_checks(url: str, *, client: Any | None = None, timeout: float = 240, poll: float = 1.0,
               ask: Any | None = None, sleep=time.sleep) -> list[Record]:
    client = client or terminal.HttpClient(url)
    records: list[Record] = []
    ids: dict[str, str] = {}

    # 1 - reachable ---------------------------------------------------------
    rec = Record(1, "server reachable", "GET /health", {}, "service multi-agent-server with a four-stage pipeline")
    try:
        status, health = client.get("/health")
    except terminal.ServerUnavailable as exc:
        rec.observed = str(exc)
        records.append(rec)
        return records                                   # nothing else can run
    pipeline = health.get("pipeline", [])
    rec.observed = (f"HTTP {status}; pipeline {' -> '.join(pipeline)}; roles {health.get('roles')}; "
                    f"models {health.get('models')}; max_revisions {health.get('max_revisions')}")
    rec.passed = (status == 200 and health.get("service") == "multi-agent-server"
                  and pipeline == ["planner", "worker", "reviewer", "human"]
                  and health.get("decisions") == ["accept", "partially_accept", "reject"])
    rec.detail = {k: health.get(k) for k in ("pipeline", "roles", "models", "max_revisions", "stage_timeout_seconds", "auth", "audit")}
    rec.detail["audit"] = {k: _rel(Path(v)) for k, v in (health.get("audit") or {}).items()}
    records.append(rec)
    if not rec.passed:
        return records

    # 2 - full workflow to the human gate -----------------------------------
    body = {"feature": "budgeting", "request": REQUEST_ACCEPT, "context": CONTEXT}
    rec = Record(2, "full workflow reaches the human gate", "POST /workflow + poll /status", body,
                 "planner, worker and reviewer complete; state awaiting_human_review with plan, evidence and review")
    status, started = client.post("/workflow", body)
    if status != 202:
        rec.observed = f"HTTP {status}: {started.get('error')}"
        records.append(rec)
        return records
    ids["accept"] = started["workflow_id"]
    rec.detail["workflow_ids"] = dict(ids)              # recorded now, so a failed run still snapshots its audit
    final = _wait_for_gate(client, ids["accept"], timeout, poll, sleep)
    _s, full = client.get(f"/workflow/{ids['accept']}")
    plan, result, review = full.get("plan") or {}, full.get("result") or {}, full.get("review") or {}
    ok_evidence = [r for r in result.get("evidence", []) if r["status"] == "ok"]
    roles_done = [s["role"] for s in final.get("stages", []) if s["status"] in ("completed", "timed_out")]
    rec.passed = (final.get("state") == State.AWAITING_HUMAN_REVIEW
                  and all(role in roles_done for role in ("planner", "worker", "reviewer"))
                  and len(plan.get("tasks", [])) >= 1 and len(ok_evidence) >= 1 and bool(review.get("verdict")))
    summary = _stage_summary(final)
    rec.observed = (f"{ids['accept']} -> {final.get('state')}; stages {summary['stages']}; "
                    f"plan {len(plan.get('tasks', []))} tasks ({(plan.get('meta') or {}).get('source')}); "
                    f"evidence {len(ok_evidence)}/{len(result.get('evidence', []))} ok; "
                    f"review {review.get('verdict')} ({(review.get('meta') or {}).get('source')})"
                    + (f"; error {final.get('error')}" if final.get("error") else ""))
    if summary["fallbacks"]:
        rec.observed += f"  (degraded: fallback in {summary['fallbacks']})"
    rec.detail.update({
        **summary,
        "plan_source": (plan.get("meta") or {}).get("source"),
        "plan_tasks": [f"{t['id']} {t['kind']} {t.get('endpoint', '')}".strip() for t in plan.get("tasks", [])],
        "evidence": [f"{r['task_id']} {r['endpoint']} {r['status']}" for r in result.get("evidence", [])],
        "spending_sources": sorted({str(r["summary"].get("spending_source")) for r in ok_evidence
                                    if isinstance(r.get("summary"), dict) and "spending_source" in r["summary"]}),
        "finding_count": len(result.get("findings", [])),
        "result_source": (result.get("meta") or {}).get("source"),
        "review_verdict": review.get("verdict"),
        "review_source": (review.get("meta") or {}).get("source"),
        "criteria_met": f"{sum(1 for c in review.get('criteria', []) if c.get('met') is True)}/{len(review.get('criteria', []))}",
        "defects": len(review.get("defects", [])),
        "risks": review.get("risks", []),
        "escalated": review.get("escalated"),
    })
    records.append(rec)
    if final.get("state") != State.AWAITING_HUMAN_REVIEW:
        return records

    # 3 - the gate holds ------------------------------------------------------
    rec = Record(3, "response withheld until a person decides", "GET /workflow/<id>/response", {"workflow_id": ids["accept"]},
                 "HTTP 409 with awaiting_decision true; the workflow is listed under /workflows/pending")
    status, withheld = client.get(f"/workflow/{ids['accept']}/response")
    _s, pending = client.get("/workflows/pending")
    listed = [w["workflow_id"] for w in pending.get("workflows", [])]
    rec.observed = f"HTTP {status}: {withheld.get('error')}; pending {pending.get('count')} incl. this one: {ids['accept'] in listed}"
    rec.passed = status == 409 and withheld.get("awaiting_decision") is True and ids["accept"] in listed
    rec.detail = {"status": status, "pending_count": pending.get("count"), "options": pending.get("options")}
    records.append(rec)

    # 4 - accept releases the response -----------------------------------------
    decision = {"decision": "accept", "note": "", "by": "validate"}
    rec = Record(4, "accept releases the final response", "POST /workflow/<id>/decision", decision,
                 "state accepted; GET /response is 200 with released true and the Worker's answer")
    status, decided = client.post(f"/workflow/{ids['accept']}/decision", decision)
    status2, released = client.get(f"/workflow/{ids['accept']}/response")
    answer = (released.get("answer") or "") if isinstance(released, dict) else ""
    rec.observed = (f"decision HTTP {status} -> {decided.get('state')}; response HTTP {status2}, released "
                    f"{released.get('released')}, answer {len(answer)} chars, decided_by {released.get('decided_by')}")
    rec.passed = (status == 200 and decided.get("state") == State.ACCEPTED and status2 == 200
                  and released.get("released") is True and bool(answer))
    rec.detail = {"answer": answer[:400], "risks": released.get("risks"), "evidence_sources": released.get("evidence_sources")}
    records.append(rec)

    # 5 - a rejected workflow is recorded ------------------------------------------
    body = {"feature": "budgeting", "request": REQUEST_REJECT, "context": CONTEXT}
    rec = Record(5, "rejected workflow recorded, nothing released", "POST /workflow, then decision reject",
                 {**body, "decision": "reject", "note": REJECT_NOTE},
                 "state rejected; GET /response is 200 with released false and the note kept")
    status, started = client.post("/workflow", body)
    if status == 202:
        ids["reject"] = started["workflow_id"]
        rec.detail["workflow_ids"] = dict(ids)
        final = _wait_for_gate(client, ids["reject"], timeout, poll, sleep)
        if final.get("state") == State.AWAITING_HUMAN_REVIEW:
            status, decided = client.post(f"/workflow/{ids['reject']}/decision",
                                          {"decision": "reject", "note": REJECT_NOTE, "by": "validate"})
            status2, response = client.get(f"/workflow/{ids['reject']}/response")
            rec.observed = (f"{ids['reject']} -> {decided.get('state')}; response HTTP {status2}, released "
                            f"{response.get('released')}, answer {response.get('answer')!r}, note kept "
                            f"{response.get('correction_note') == REJECT_NOTE}")
            rec.passed = (status == 200 and decided.get("state") == State.REJECTED and status2 == 200
                          and response.get("released") is False and response.get("answer") is None
                          and response.get("correction_note") == REJECT_NOTE)
            rec.detail.update({**_stage_summary(final), "review_verdict": response.get("review_verdict")})
        else:
            rec.observed = f"{ids['reject']} -> {final.get('state')}: {final.get('error')}"
    else:
        rec.observed = f"HTTP {status}: {started.get('error')}"
    records.append(rec)

    # 6 - audit files ----------------------------------------------------------------
    audit = health.get("audit") or {}
    rec = Record(6, "audit files written", "read workflow_history.jsonl and coordination_audit.jsonl",
                 {k: _rel(Path(v)) for k, v in audit.items()},
                 "both files exist and hold every stage, handoff and the human decisions of the workflows above")
    rec.detail["workflow_ids"] = dict(ids)
    history_path, coord_path = Path(audit.get("workflow_history", "")), Path(audit.get("coordination_audit", ""))
    if history_path.is_file() and coord_path.is_file():
        history = _read_jsonl(history_path, set(ids.values()))
        coordination = _read_jsonl(coord_path, set(ids.values()))
        events = {r["event"] for r in history}
        decisions_seen = {r["decision"] for r in coordination}
        human = [r for r in coordination if r["decision"] == "human_decision"]
        needed_events = {"workflow_created", "state_changed", "stage_started", "stage_completed", "workflow_completed"}
        needed_decisions = {"request_accepted", "handoff", "awaiting_decision", "human_decision"}
        rec.passed = (needed_events <= events and needed_decisions <= decisions_seen
                      and {r["detail"].get("decision") for r in human} >= {"accept"} | ({"reject"} if "reject" in ids else set())
                      and all(r["actor"] == "human" for r in human)
                      and all(r["ts"].endswith("+00:00") for r in history + coordination))
        rec.observed = (f"{len(history)} history records, {len(coordination)} coordination records for "
                        f"{len(ids)} workflows; events {sorted(events)}; decisions {sorted(decisions_seen)}")
        rec.detail.update({"history_records": len(history), "coordination_records": len(coordination),
                           "events": sorted(events), "decisions": sorted(decisions_seen),
                           "human_decisions": [r["detail"].get("decision") for r in human]})
    else:
        rec.observed = f"missing: {[str(p) for p in (history_path, coord_path) if not p.is_file()]}"
    records.append(rec)

    # 7 - handoff contracts (deterministic) ------------------------------------------
    rec = Record(7, "handoff contracts reject off-contract outputs", "contracts.validate_plan / validate_result / validate_review",
                 {"plan": "unknown endpoint + another customer", "result": "invented figure", "review": "accept with an unmet criterion"},
                 "each is rejected with the reasons listed; nothing off-contract reaches the next role")
    rec.detail, rec.passed = _contract_probe()
    rec.observed = "; ".join(f"{k}: {v['errors'][0]}" for k, v in rec.detail.items()) if rec.passed else json.dumps(rec.detail)[:300]
    records.append(rec)

    # 8 - dependency down (in-process, same server code) ------------------------------
    rec = Record(8, "feature API down -> structured error, no invented result", "in-process server, budgeting -> " + UNREACHABLE_URL,
                 {"feature": "budgeting", "request": REQUEST_ACCEPT, "context": CONTEXT},
                 "state failed; error names the unreachable URL; evidence records carry the errors; worker_blocked audited")
    try:
        rec.observed, rec.passed, rec.detail = _down_probe(ask)
    except Exception as exc:  # the probe itself must never crash the record
        rec.observed = f"probe error: {type(exc).__name__}: {exc}"
    records.append(rec)

    # 9 - coordination metrics from the audit ---------------------------------------
    scope = ",".join(ids.values())
    rec = Record(9, "coordination metrics computed from the audit files", "GET /metrics", {"workflows": scope},
                 "rates and stage times derived from the two JSONL files, covering the workflows above")
    status, metrics = client.get(f"/metrics?workflows={scope}")
    wf = metrics.get("workflows", {}) if isinstance(metrics, dict) else {}
    rec.passed = (status == 200 and wf.get("total", 0) >= len(ids) and wf.get("decided", 0) >= len(ids)
                  and metrics.get("plan_acceptance_rate") is not None
                  and metrics.get("worker_completion_rate") is not None
                  and metrics.get("human_acceptance_rate") is not None)
    rec.observed = (f"HTTP {status}; workflows {wf.get('total')} ({wf.get('decided')} decided); "
                    f"plan acceptance {metrics.get('plan_acceptance_rate')}, worker completion {metrics.get('worker_completion_rate')}, "
                    f"handoff success {metrics.get('handoff_success_rate')}, defect yield {metrics.get('reviewer_defect_yield')}, "
                    f"rework {metrics.get('rework_ratio')}, fallback {metrics.get('fallback_rate')}, "
                    f"human acceptance {metrics.get('human_acceptance_rate')}; stage s {metrics.get('stage_seconds')}; "
                    f"end-to-end s {metrics.get('end_to_end_seconds')}")
    rec.detail = metrics if isinstance(metrics, dict) else {"body": metrics}
    records.append(rec)

    return records


def _read_jsonl(path: Path, workflow_ids: set[str]) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("workflow_id") in workflow_ids:
            records.append(record)
    return records


def _contract_probe() -> tuple[dict[str, Any], bool]:
    plan = {"objective": "x", "tasks": [
        {"id": "t1", "kind": "api", "endpoint": "/api/customers", "params": {}},
        {"id": "t2", "kind": "api", "endpoint": "/api/budgets/summary", "params": {"customer_id": 2, "month": 9, "year": 2026}},
    ], "success_criteria": ["y"]}
    good_plan = contracts.validate_plan({"objective": "x", "tasks": [
        {"id": "t1", "kind": "api", "endpoint": "/api/budgets/summary", "params": CONTEXT, "evidence": "e"},
        {"id": "t2", "kind": "analysis", "depends_on": ["t1"], "instruction": "judge", "evidence": "e"},
    ], "success_criteria": ["Every over-budget category is named"]}, "budgeting", CONTEXT)
    evidence = [{"task_id": "t1", "status": "ok", "endpoint": "/api/budgets/summary", "params": CONTEXT,
                 "summary": {"budget_count": 7, "totals": {"total_spent": 2169.97}}}]
    result = {"findings": [{"task_id": "t2", "statement": "You spent $9,999.00.", "evidence": ["t1"]}],
              "answer": "Total $9,999.00.", "gaps": []}
    review = {"verdict": "accept", "summary": "fine", "criteria": [{"index": 1, "met": False, "note": "not shown"}],
              "defects": [], "risks": [], "revision_notes": []}
    outcome: dict[str, Any] = {}
    for name, fn in (("plan", lambda: contracts.validate_plan(plan, "budgeting", CONTEXT)),
                     ("result", lambda: contracts.validate_result(result, good_plan, evidence)),
                     ("review", lambda: contracts.validate_review(review, good_plan, evidence))):
        try:
            fn()
            outcome[name] = {"rejected": False, "errors": []}
        except contracts.ContractError as exc:
            outcome[name] = {"rejected": True, "errors": exc.errors}
    return outcome, all(v["rejected"] for v in outcome.values())


def _down_probe(ask: Any | None) -> tuple[str, bool, dict[str, Any]]:
    """The server code against an unreachable budgeting URL, in this process."""
    from multi_agent_server.orchestrator import InlineExecutor
    from multi_agent_server.server import create_app

    previous = config.SERVICE_URLS["budgeting"]
    config.SERVICE_URLS["budgeting"] = UNREACHABLE_URL
    try:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(data_dir=Path(tmp) / "data", audit_dir=Path(tmp) / "audit",
                             executor=InlineExecutor(), ask=ask, api_token="")
            test_client = app.test_client()
            body = test_client.post("/workflow", json={"feature": "budgeting", "request": REQUEST_ACCEPT, "context": CONTEXT}).get_json()
            result = test_client.get(f"/workflow/{body['workflow_id']}/result").get_json()["result"] or {}
            coordination = [json.loads(line) for line in (Path(tmp) / "audit" / "coordination_audit.jsonl").read_text().splitlines() if line.strip()]
    finally:
        config.SERVICE_URLS["budgeting"] = previous
    errors = [r["error"] for r in result.get("evidence", []) if r["status"] != "ok"]
    blocked = [r for r in coordination if r["decision"] == "worker_blocked"]
    passed = (body["state"] == State.FAILED and UNREACHABLE_URL in (body.get("error") or "")
              and bool(errors) and all(UNREACHABLE_URL in e for e in errors) and len(blocked) == 1
              and (result.get("meta") or {}).get("source") == "blocked" and not result.get("findings"))
    observed = f"{body['workflow_id']} -> {body['state']}; error: {body.get('error')}"
    detail = {"state": body["state"], "error": body.get("error"), "evidence_errors": errors,
              "worker_blocked": bool(blocked), "result_source": (result.get("meta") or {}).get("source"),
              "coordination": [r["decision"] for r in coordination]}
    return observed, passed, detail


def print_report(url: str, records: list[Record]) -> None:
    rule = "=" * 72
    print(rule)
    print("  SmartBank Multi-Agent Server - terminal validation")
    print(f"  server:  {url}")
    print(f"  commit:  {_git_sha()}")
    print(rule)
    for r in records:
        tag = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        print(f"  {tag}  {r.n}. {r.check}")
        print(f"        call:      {r.call}  {json.dumps(r.arguments)[:160] if r.arguments else ''}")
        print(f"        expected:  {r.expected}")
        print(f"        observed:  {r.observed}")
    skipped = sum(1 for r in records if r.skipped)
    passed = sum(1 for r in records if r.passed and not r.skipped)
    print(rule)
    print(f"  {passed}/{len(records) - skipped} checks passed, {skipped} skipped")
    print(rule)


def write_evidence(url: str, records: list[Record]) -> list[Path]:
    """The test record plus a snapshot of the two audit files for the workflows this run created."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ids: set[str] = set()
    audit: dict[str, str] = {}
    for r in records:
        ids |= set((r.detail.get("workflow_ids") or {}).values())
        if r.n == 1:
            audit = r.detail.get("audit") or {}
    written: list[Path] = []
    snapshot_dir = EVIDENCE_AUDIT_DIR / f"validation-{stamp}"
    if ids and audit:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for name, source in (("workflow_history.jsonl", audit.get("workflow_history")),
                             ("coordination_audit.jsonl", audit.get("coordination_audit"))):
            source_path = Path(source) if source and Path(source).is_absolute() else (REPO_ROOT / source if source else None)
            if source_path and source_path.is_file():
                lines = [json.dumps(r, ensure_ascii=False) for r in _read_jsonl(source_path, ids)]
                target = snapshot_dir / name
                target.write_text("\n".join(lines) + "\n", encoding="utf-8")
                written.append(target)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "multi-agent-terminal-validation",
        "timestamp": stamp,
        "server_url": url,
        "implementation_version": _git_sha(),
        "workflow_ids": sorted(ids),
        "audit_snapshot": [_rel(p) for p in written],
        "records": [asdict(r) for r in records],
        "passed": all(r.passed for r in records),
    }
    report = EVIDENCE_DIR / f"multi-agent-validation-{stamp}.json"
    report.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return [report, *written]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the shared Multi-Agent Server.")
    parser.add_argument("--url", default=config.local_url())
    parser.add_argument("--timeout", type=float, default=240, help="seconds to wait for each workflow to reach the human gate")
    parser.add_argument("--evidence", action="store_true",
                        help="write docs/evidence/multi-agent-validation-<ts>.json and an audit snapshot under docs/evidence/multi_agent/")
    args = parser.parse_args(argv)

    records = run_checks(args.url, timeout=args.timeout)
    print_report(args.url, records)
    if args.evidence:
        for path in write_evidence(args.url, records):
            print(f"  evidence: {_rel(path)}")
    return 0 if all(r.passed for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
