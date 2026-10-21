"""Multi-Agent Workflow Review mode - Bao (Release 2).

Reviews the Multi-Agent Server's own evidence, the two audit files Lecture 10
names (workflow_history.jsonl and coordination_audit.jsonl), and has the model
write the review entry with implementation and review recommendations.

ACT reads the audit files, never the server's memory: the latest workflows are
rebuilt record by record (stages, verdicts, revisions, the human decision, the
release), and the coordination metrics come from `multi_agent_server.metrics`,
the same figures `/metrics` serves. OBSERVE rejects an entry that names a
workflow id the records do not contain, drops one of the four stages, misquotes
a decision or a metric, or calls ATTENTION a PASS; ADAPT retries with that
complaint. With no audit file in reach the run stops before any token is spent.

Where the records come from, first match wins:
  MULTI_AGENT_AUDIT_DIR         an explicit folder with the two files
  multi_agent_server/data/audit the running server's own audit folder
  docs/evidence/multi_agent/    the newest validation snapshot
  docs/release-2/multi-agent/   a feature's committed evidence folder
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict
from agentic.modes._review_common import DOCS_DIR, REPO_ROOT, has_number, line_for, rate, read_jsonl, rel

PROMPT_FAMILY = "_multi_agent_review"
HISTORY_FILE = "workflow_history.jsonl"
COORDINATION_FILE = "coordination_audit.jsonl"
ROLES = ("planner", "worker", "reviewer", "human")
DECISIONS = ("accept", "partially_accept", "reject")
REQUIRED_LINES = ("workflows", "stages", "decisions", "metrics", "recommendation", "verdict")
METRIC_LABELS = {"plan_acceptance_rate": "plan acceptance", "worker_completion_rate": "worker completion",
                 "handoff_success_rate": "handoff success", "human_acceptance_rate": "human acceptance"}
WORKFLOW_ID = re.compile(r"wf_[0-9a-f]{8}")
START_HINT = ("run a workflow first: python -m multi_agent_server.server, then "
              "python -m multi_agent_server.run --request \"...\" (or python -m multi_agent_server.validate --evidence)")


def _limit() -> int:
    try:
        return max(1, int(os.getenv("MULTI_AGENT_REVIEW_LIMIT", "8")))
    except ValueError:
        return 8


def _candidate_dirs() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    if os.getenv("MULTI_AGENT_AUDIT_DIR"):
        found.append((Path(os.environ["MULTI_AGENT_AUDIT_DIR"]), "MULTI_AGENT_AUDIT_DIR"))
    found.append((REPO_ROOT / "multi_agent_server" / "data" / "audit", "the running server's audit folder"))
    snapshots = sorted((DOCS_DIR / "evidence" / "multi_agent").glob("validation-*"), reverse=True)
    found.extend((p, "the newest validation snapshot") for p in snapshots[:1])
    committed = sorted(p for p in (DOCS_DIR / "release-2" / "multi-agent").glob("*") if p.is_dir())
    found.extend((p, f"the committed {p.name} evidence") for p in committed)
    return found


def audit_dir() -> tuple[Path | None, str]:
    """The first folder that holds both audit files with records in them."""
    for path, label in _candidate_dirs():
        if (path / HISTORY_FILE).is_file() and (path / COORDINATION_FILE).is_file():
            if (path / HISTORY_FILE).stat().st_size and (path / COORDINATION_FILE).stat().st_size:
                return path, label
    return None, ""


def _workflow_facts(wid: str, history: list[dict], coordination: list[dict]) -> dict[str, Any]:
    created = next((r for r in history if r.get("event") == "workflow_created"), None)
    stages: dict[str, dict[str, Any]] = {role: {"started": 0, "completed": 0, "fallback": False} for role in ROLES}
    final_state = ""
    error = ""
    for r in history:
        role, event, detail = r.get("role", ""), r.get("event", ""), r.get("detail") or {}
        if role in stages and event == "stage_started":
            stages[role]["started"] += 1
        if role in stages and (event == "stage_completed" or (event == "stage_timed_out" and detail.get("fallback"))):
            stages[role]["completed"] += 1
            if detail.get("fallback"):
                stages[role]["fallback"] = True
        if event == "state_changed":
            final_state = str(detail.get("to", r.get("state", "")))
        if detail.get("error"):
            error = str(detail["error"])
    decision, decided_by, released, verdict, escalated = None, "", None, "", False
    revisions = 0
    for r in coordination:
        kind, detail = r.get("decision", ""), r.get("detail") or {}
        if kind == "human_decision":
            decision, decided_by = str(detail.get("decision", "")), str(detail.get("by", ""))
        elif kind == "response_released":
            released = True
        elif kind == "response_withheld":
            released = False
        elif kind == "verdict_recorded":
            verdict = str(detail.get("verdict", ""))
        elif kind == "escalated_to_human":
            escalated = True
        elif kind == "revision_requested":
            revisions += 1
    return {
        "workflow_id": wid,
        "feature": str((created or history[0] if history else {}).get("feature", "")),
        "request": str(((created or {}).get("detail") or {}).get("request", "")),
        "created_at": str((created or {}).get("ts", "")),
        "final_state": final_state or str((history or coordination)[-1].get("state", "")),
        "stages": stages,
        "fallbacks": sum(1 for s in stages.values() if s["fallback"]),
        "revisions": revisions,
        "verdict": verdict,
        "escalated": escalated,
        "decision": decision if decision in DECISIONS else None,
        "decided_by": decided_by,
        "released": released,
        "failed": final_state == "failed",
        "error": error,
    }


class MultiAgentReviewMode(Mode):
    key = "multi_agent_review"
    label = "Multi-Agent Workflow Review"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=("Review the Multi-Agent workflow evidence (workflow_history.jsonl and "
                  "coordination_audit.jsonl) and produce review recommendations grounded in those records"),
            checks=[
                "both audit files exist and hold records (the running server, a validation snapshot or committed evidence)",
                "every reviewed workflow is rebuilt from its records: stages, reviewer verdict, revisions, the human decision, the release",
                "the coordination metrics (plan acceptance, worker completion, handoff success, human acceptance) come from the same records",
                "the entry names only workflow ids in the records, every one of the four stages, and quotes each decision and metric exactly",
                "a workflow that failed, a fallback stage or a handoff anomaly makes the verdict ATTENTION, never PASS",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        folder, source = audit_dir()
        if folder is None:
            return Evidence(ok=False, summary=f"no Multi-Agent audit files found; {START_HINT}")
        history = read_jsonl(folder / HISTORY_FILE)
        coordination = read_jsonl(folder / COORDINATION_FILE)
        ids = [r.get("workflow_id") for r in history if r.get("event") == "workflow_created"]
        ids = [i for i in ids if isinstance(i, str)]
        if not ids:
            return Evidence(ok=False, summary=f"{rel(folder)} holds no workflow_created record; {START_HINT}")
        reviewed = list(dict.fromkeys(ids))[-_limit():]                    # the latest workflows, in creation order
        chosen = set(reviewed)
        history = [r for r in history if r.get("workflow_id") in chosen]
        coordination = [r for r in coordination if r.get("workflow_id") in chosen]

        try:
            from multi_agent_server import metrics as ma_metrics
            metrics = ma_metrics.compute(history, coordination)
        except Exception as exc:                                             # the server package is not installed here
            metrics = {"error": f"{type(exc).__name__}: {exc}", "counts": {}, "workflows": {}}

        workflows = [
            _workflow_facts(wid, [r for r in history if r["workflow_id"] == wid],
                            [r for r in coordination if r["workflow_id"] == wid])
            for wid in reviewed
        ]
        stage_totals = {role: {"started": sum(w["stages"][role]["started"] for w in workflows),
                               "completed": sum(w["stages"][role]["completed"] for w in workflows)}
                        for role in ROLES}
        decisions = Counter(w["decision"] for w in workflows if w["decision"])
        pending = sum(1 for w in workflows if not w["decision"] and not w["failed"])
        failed = sum(1 for w in workflows if w["failed"])
        fallbacks = sum(w["fallbacks"] for w in workflows)
        revisions = sum(w["revisions"] for w in workflows)
        anomalies = int((metrics.get("counts") or {}).get("handoff_anomalies", 0) or 0)
        attention = failed > 0 or fallbacks > 0 or anomalies > 0 or any(w["error"] for w in workflows)
        rates = {key: metrics.get(key) for key in METRIC_LABELS}

        facts = {
            "source": rel(folder), "source_kind": source,
            "history_records": len(history), "coordination_records": len(coordination),
            "count": len(workflows), "ids": reviewed, "workflows": workflows,
            "stage_totals": stage_totals, "decisions": dict(decisions), "pending": pending, "failed": failed,
            "fallbacks": fallbacks, "revisions": revisions, "handoff_anomalies": anomalies,
            "rates": rates, "metrics": metrics, "attention": attention,
        }
        outcomes = ", ".join(
            f"{w['workflow_id']} {w['final_state']}" + (f" ({w['decision']} by {w['decided_by']})" if w["decision"] else "")
            for w in workflows)
        stage_text = ", ".join(f"{role} {t['completed']}/{t['started']}" for role, t in stage_totals.items())
        return Evidence(
            ok=True,
            summary=(f"{len(workflows)} workflow(s) from {source} ({rel(folder)}): {outcomes}. "
                     f"Stages {stage_text}; fallbacks {fallbacks}; revisions {revisions}. "
                     f"Decisions accept {decisions.get('accept', 0)}, partially_accept {decisions.get('partially_accept', 0)}, "
                     f"reject {decisions.get('reject', 0)}, pending {pending}, failed {failed}. "
                     + ", ".join(f"{label} {rate(rates[key])}" for key, label in METRIC_LABELS.items())),
            facts=facts,
            degraded=fallbacks > 0,
            note=(f"{fallbacks} model stage(s) answered by a fallback (the server's model was unavailable); "
                  "the workflow records are complete but those stages carry no model output" if fallbacks else ""),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(PROMPT_FAMILY, "review_system.txt", "review_task.txt")
        f = evidence.facts
        lines = [f"Source: {f['source']} ({f['source_kind']}), {f['history_records']} history records, "
                 f"{f['coordination_records']} coordination records", "Workflows (oldest first):"]
        for w in f["workflows"]:
            stages = ", ".join(
                f"{role} {s['completed']}/{s['started']}" + (" fallback" if s["fallback"] else "")
                for role, s in w["stages"].items())
            decision = f"{w['decision']} by {w['decided_by']}" if w["decision"] else ("failed" if w["failed"] else "pending")
            release = {True: "released", False: "withheld", None: "no response yet"}[w["released"]]
            lines.append(
                f"- {w['workflow_id']} ({w['feature']}, created {w['created_at']}): request \"{w['request'][:120]}\"; "
                f"final state {w['final_state']}; stages {stages}; reviewer verdict {w['verdict'] or 'none'}; "
                f"revisions {w['revisions']}; escalated {'yes' if w['escalated'] else 'no'}; "
                f"human decision {decision}; response {release}" + (f"; error: {w['error'][:120]}" if w["error"] else ""))
        totals = f["stage_totals"]
        d = f["decisions"]
        lines += [
            "Totals: " + ", ".join(f"{role} {t['completed']}/{t['started']}" for role, t in totals.items())
            + f"; fallbacks {f['fallbacks']}; revisions {f['revisions']}; handoff anomalies {f['handoff_anomalies']}",
            f"Decisions: accept {d.get('accept', 0)}, partially_accept {d.get('partially_accept', 0)}, "
            f"reject {d.get('reject', 0)}, pending {f['pending']}, failed {f['failed']}",
            "Metrics: " + ", ".join(f"{label} {rate(f['rates'][key])}" for key, label in METRIC_LABELS.items()),
            f"Required verdict word: {'ATTENTION' if f['attention'] else 'PASS'}",
        ]
        correction = ""
        if feedback:
            correction = (f"\n\nYour previous entry was rejected: {feedback}. Fix exactly that. Keep the six-line "
                          "format and copy workflow ids, decisions, counts and metrics from the evidence verbatim.")
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

        invented = sorted(set(WORKFLOW_ID.findall(output)) - set(f["ids"]))
        if invented:
            reasons.append("it named workflow id(s) that are not in the evidence: " + ", ".join(invented)
                           + "; use only the listed ids")

        workflows_line = lines["workflows"]
        if workflows_line:
            if not has_number(workflows_line, f["count"]):
                reasons.append(f"the Workflows line did not state the number reviewed ({f['count']}) as a number")
            missing = [wid for wid in f["ids"] if wid not in workflows_line]
            if missing:
                reasons.append("the Workflows line did not list these workflow ids: " + ", ".join(missing))

        stages_line = lines["stages"].lower()
        if stages_line:
            for role in ROLES:
                t = f["stage_totals"][role]
                match = re.search(rf"\b{role}\s+(\d+)\s*/\s*(\d+)", stages_line)
                if not match:
                    reasons.append(f"the Stages line must name every stage: planner, worker, reviewer and human "
                                   f"(it dropped {role} {t['completed']}/{t['started']})")
                elif match.groups() != (str(t["completed"]), str(t["started"])):
                    reasons.append(f"the Stages line must read {role} {t['completed']}/{t['started']}")
            for word, value in (("fallbacks", f["fallbacks"]), ("revisions", f["revisions"])):
                match = re.search(rf"\b{word}\s+(\d+)", stages_line)
                if not match or match.group(1) != str(value):
                    reasons.append(f"the Stages line must state {word} {value}")

        decisions_line = lines["decisions"].lower()
        if decisions_line:
            d = f["decisions"]
            for word in DECISIONS:
                match = re.search(rf"(?<![a-z_]){word}\s+(\d+)", decisions_line)
                if not match or match.group(1) != str(d.get(word, 0)):
                    reasons.append(f"the Decisions line must state {word} {d.get(word, 0)}")
            for w in f["workflows"]:
                expected = w["decision"] or ("failed" if w["failed"] else "pending")
                match = re.search(rf"{w['workflow_id']}\s+(accept|partially_accept|reject|pending|failed)", decisions_line)
                if not match:
                    reasons.append(f"the Decisions line must list {w['workflow_id']} {expected}")
                elif match.group(1) != expected:
                    reasons.append(f"the Decisions line misquotes {w['workflow_id']}: the records say {expected}, "
                                   f"not {match.group(1)}")

        metrics_line = lines["metrics"].lower()
        if metrics_line:
            for key, label in METRIC_LABELS.items():
                expected = rate(f["rates"][key])
                match = re.search(rf"{label}\s+([0-9]+\.[0-9]+|n/a)", metrics_line)
                if not match or match.group(1) != expected:
                    reasons.append(f"the Metrics line must state {label} {expected}")

        verdict_line = lines["verdict"].lower()
        if verdict_line:
            expected_word = "attention" if f["attention"] else "pass"
            words = re.findall(r"\b(pass|attention)\b", verdict_line)
            if not words or words[0] != expected_word:
                why = (f"{f['failed']} failed workflow(s), {f['fallbacks']} fallback stage(s), "
                       f"{f['handoff_anomalies']} handoff anomal(ies)")
                reasons.append(f"the Verdict line must start with {expected_word.upper()}: the records show {why}")

        recommendation = lines["recommendation"]
        if recommendation and len(recommendation.split(":", 1)[-1].strip()) < 20:
            reasons.append("the Recommendation line must say what to keep or change, in at least one full sentence")

        return Verdict(ok=not reasons, reasons=reasons)
