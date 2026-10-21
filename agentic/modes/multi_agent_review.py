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

Where the records come from:
  MULTI_AGENT_AUDIT_DIR         an explicit folder: used alone, never swapped for another
otherwise the first of these that holds records:
  <MULTI_AGENT_DATA_DIR>/audit  the running server's own audit folder (default multi_agent_server/data/audit)
  docs/evidence/multi_agent/    the newest validation snapshot
  docs/release-2/multi-agent/   a feature's committed evidence folder

Records the review cannot trust are never reviewed as if they were complete:
a line that is not JSON or lacks the fields the server writes is left out and
makes the verdict ATTENTION, so do metrics that cannot be computed, and the
lines of a decision the server rolled back (a decision_rolled_back marker
follows them) are void, so that decision is not counted.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict
from agentic.modes._review_common import DOCS_DIR, REPO_ROOT, has_number, line_for, rate, read_jsonl_counted, rel

PROMPT_FAMILY = "_multi_agent_review"
HISTORY_FILE = "workflow_history.jsonl"
COORDINATION_FILE = "coordination_audit.jsonl"
ROLES = ("planner", "worker", "reviewer", "human")
DECISIONS = ("accept", "partially_accept", "reject")
REQUIRED_LINES = ("workflows", "stages", "decisions", "metrics", "recommendation", "verdict")
METRIC_LABELS = {"plan_acceptance_rate": "plan acceptance", "worker_completion_rate": "worker completion",
                 "handoff_success_rate": "handoff success", "human_acceptance_rate": "human acceptance"}
ID_TOKEN = re.compile(r"(?<![0-9A-Za-z_])wf_[0-9A-Za-z_]+")    # anything id-like, so a longer or altered id is caught
START_HINT = ("run a workflow first: python -m multi_agent_server.server, then "
              "python -m multi_agent_server.run --request \"...\" (or python -m multi_agent_server.validate --evidence)")
# The fields multi_agent_server/audit.py writes on every line; a line without them is not the server's.
HISTORY_FIELDS = (("ts", str), ("workflow_id", str), ("event", str), ("role", str), ("detail", dict))
COORDINATION_FIELDS = (("ts", str), ("workflow_id", str), ("decision", str), ("detail", dict))
ROLLED_BACK = "decision_rolled_back"


def _well_formed(record: dict[str, Any], fields: tuple[tuple[str, type], ...]) -> bool:
    return all(isinstance(record.get(name), kind) for name, kind in fields)


def _is_decision_line(record: dict[str, Any], kind: str) -> bool:
    """A line the server writes as part of a human decision (see Orchestrator.decide)."""
    if kind == "event":
        return ((record["event"] == "state_changed" and record["detail"].get("from") == "awaiting_human_review")
                or (record["event"] == "stage_completed" and record["role"] == "human")
                or record["event"] == "workflow_completed")
    return record["decision"] in ("human_decision", "response_released", "response_withheld")


def _void_rolled_back(records: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """The records without the lines of a decision the server took back.

    When a decision's audit lines cannot all be written, the server restores the
    workflow and appends a decision_rolled_back marker: the decision lines just
    above it, for that workflow, are void. They are dropped here; the marker is
    kept, so the server's metrics still count the rollback."""
    void: set[int] = set()
    positions: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        positions.setdefault(r["workflow_id"], []).append(i)
    for indexes in positions.values():
        for n, i in enumerate(indexes):
            if records[i][kind] != ROLLED_BACK:
                continue
            for j in reversed(indexes[:n]):
                if not _is_decision_line(records[j], kind):
                    break
                void.add(j)
    return [r for i, r in enumerate(records) if i not in void]


def _server_audit_dir() -> Path:
    """Where the running server writes its audit files, from the same settings as multi_agent_server.config."""
    return Path(os.getenv("MULTI_AGENT_DATA_DIR") or (REPO_ROOT / "multi_agent_server" / "data")) / "audit"


def _limit() -> int:
    try:
        return max(1, int(os.getenv("MULTI_AGENT_REVIEW_LIMIT", "8")))
    except ValueError:
        return 8


def _candidate_dirs() -> list[tuple[Path, str]]:
    if os.getenv("MULTI_AGENT_AUDIT_DIR"):
        # An explicit folder is the only one: reviewing some other folder's records instead would mislead.
        return [(Path(os.environ["MULTI_AGENT_AUDIT_DIR"]), "MULTI_AGENT_AUDIT_DIR")]
    found: list[tuple[Path, str]] = [(_server_audit_dir(), "the running server's audit folder")]
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
            explicit = os.getenv("MULTI_AGENT_AUDIT_DIR")
            where = (f"MULTI_AGENT_AUDIT_DIR ({explicit}) does not hold both audit files with records in them"
                     if explicit else "no Multi-Agent audit files found")
            return Evidence(ok=False, summary=f"{where}; {START_HINT}")
        history_lines, unreadable_history = read_jsonl_counted(folder / HISTORY_FILE)
        coordination_lines, unreadable_coordination = read_jsonl_counted(folder / COORDINATION_FILE)
        history = [r for r in history_lines if _well_formed(r, HISTORY_FIELDS)]
        coordination = [r for r in coordination_lines if _well_formed(r, COORDINATION_FIELDS)]
        left_out = (unreadable_history + unreadable_coordination
                    + len(history_lines) - len(history) + len(coordination_lines) - len(coordination))
        ids = [r["workflow_id"] for r in history if r["event"] == "workflow_created"]
        if not ids:
            return Evidence(ok=False, summary=(f"{rel(folder)} holds no readable workflow_created record"
                                               + (f" ({left_out} line(s) could not be read)" if left_out else "")
                                               + f"; {START_HINT}"))
        reviewed = list(dict.fromkeys(ids))[-_limit():]                    # the latest workflows, in creation order
        chosen = set(reviewed)
        history = _void_rolled_back([r for r in history if r["workflow_id"] in chosen], "event")
        coordination = _void_rolled_back([r for r in coordination if r["workflow_id"] in chosen], "decision")
        rolled_back = max(sum(1 for r in history if r["event"] == ROLLED_BACK),
                          sum(1 for r in coordination if r["decision"] == ROLLED_BACK))

        metrics_error = ""
        try:
            from multi_agent_server import metrics as ma_metrics
            metrics = ma_metrics.compute(history, coordination)
        except Exception as exc:                             # records the server's metrics cannot read: said, never hidden
            metrics_error = f"{type(exc).__name__}: {exc}"
            metrics = {"counts": {}, "workflows": {}}

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
        rates = {key: metrics.get(key) for key in METRIC_LABELS}
        why: list[str] = []
        if failed:
            why.append(f"{failed} failed workflow(s)")
        if fallbacks:
            why.append(f"{fallbacks} fallback stage(s)")
        if anomalies:
            why.append(f"{anomalies} handoff anomal(ies)")
        errors = [w["workflow_id"] for w in workflows if w["error"]]
        if errors:
            why.append("stage errors in " + ", ".join(errors))
        if left_out:
            why.append(f"{left_out} audit line(s) could not be read and were left out")
        if metrics_error:
            why.append(f"the metrics could not be computed ({metrics_error})")
        if rolled_back:
            why.append(f"{rolled_back} decision(s) rolled back after an audit write failure")
        attention = bool(why)

        facts = {
            "source": rel(folder), "source_kind": source,
            "history_records": len(history), "coordination_records": len(coordination),
            "count": len(workflows), "ids": reviewed, "workflows": workflows,
            "stage_totals": stage_totals, "decisions": dict(decisions), "pending": pending, "failed": failed,
            "fallbacks": fallbacks, "revisions": revisions, "handoff_anomalies": anomalies,
            "left_out": left_out, "metrics_error": metrics_error, "rolled_back": rolled_back,
            "rates": rates, "metrics": metrics, "attention": attention, "attention_reasons": why,
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
            degraded=bool(fallbacks or left_out or metrics_error),
            note="; ".join(part for part in (
                (f"{fallbacks} model stage(s) answered by a fallback (the server's model was unavailable); "
                 "the workflow records are complete but those stages carry no model output") if fallbacks else "",
                (f"{left_out} audit line(s) were not JSON or lacked the fields the server writes, so they were "
                 "left out of the review and the metrics") if left_out else "",
                f"the coordination metrics could not be computed: {metrics_error}" if metrics_error else "",
            ) if part),
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
            "Metrics: " + ", ".join(f"{label} {rate(f['rates'][key])}" for key, label in METRIC_LABELS.items())
            + (f" (could not be computed: {f['metrics_error']})" if f["metrics_error"] else ""),
            f"Audit lines left out (not JSON, or missing the fields the server writes): {f['left_out']}",
            f"Decisions rolled back after an audit write failure: {f['rolled_back']}",
            f"Required verdict word: {'ATTENTION' if f['attention'] else 'PASS'}"
            + (f" ({'; '.join(f['attention_reasons'])})" if f["attention_reasons"] else ""),
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

        invented = sorted(set(ID_TOKEN.findall(output)) - set(f["ids"]))
        if invented:
            reasons.append("it named workflow id(s) that are not in the evidence: " + ", ".join(invented)
                           + "; use only the listed ids")

        workflows_line = lines["workflows"]
        if workflows_line:
            # The count is looked for with the ids taken out, so a digit inside an id never stands in for it.
            if not has_number(ID_TOKEN.sub(" ", workflows_line), f["count"]):
                reasons.append(f"the Workflows line did not state the number reviewed ({f['count']}) as a number")
            listed = set(ID_TOKEN.findall(workflows_line))
            missing = [wid for wid in f["ids"] if wid not in listed]
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
                match = re.search(rf"(?<![0-9a-z_]){w['workflow_id']}\s+(accept|partially_accept|reject|pending|failed)",
                                  decisions_line)
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
                why = ("; ".join(f["attention_reasons"]) or
                       "no failed workflow, fallback, handoff anomaly, unreadable line or rolled-back decision")
                reasons.append(f"the Verdict line must start with {expected_word.upper()}: the records show {why}")

        recommendation = lines["recommendation"]
        if recommendation and len(recommendation.split(":", 1)[-1].strip()) < 20:
            reasons.append("the Recommendation line must say what to keep or change, in at least one full sentence")

        return Verdict(ok=not reasons, reasons=reasons)
