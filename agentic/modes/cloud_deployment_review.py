"""Cloud Deployment Report Review mode - Bao (Release 2).

Reviews the cloud deployment report the cloud owner produces and has the model
write the Cloud Deployment Review entry that supports the final human release
decision.

ACT reads one JSON report (schema in docs/deployment/cloud-deployment-report-format.md): provider and
region, the commit and workflow run, the resources, the endpoint and CRUD
checks with their status codes, the state of the four AI services (disabled by
default in the required cloud deployment), open issues, and the human release
decision once it has been made. OBSERVE rejects an entry that misquotes the
provider, the commit, a count, a status, an AI service's state, the human
decision, or that recommends approval when the release must be held; ADAPT
retries with that complaint.

The recommendation is approve only when the report describes a real
deployment (not the sample), names a cloud-deployment.yml run that succeeded,
every endpoint and CRUD check returned its expected status code, the baseline
profile has all four AI services disabled, and no issue is open. Anything
else holds the release and the verdict is ATTENTION. Until the real report
exists the sample report is reviewed, marked degraded and held, so the mode
can be demonstrated without ever approving a deployment that did not happen.

Env: CLOUD_DEPLOYMENT_REPORT (default docs/deployment/cloud-deployment-report.json;
falls back to cloud-deployment-report.sample.json next to it).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict
from agentic.modes._review_common import DOCS_DIR, line_for, read_json, rel

PROMPT_FAMILY = "_cloud_review"
DEFAULT_REPORT = DOCS_DIR / "deployment" / "cloud-deployment-report.json"
SAMPLE_REPORT = DOCS_DIR / "deployment" / "cloud-deployment-report.sample.json"
AI_SERVICES = (("ai_mode", "ai-mode"), ("mcp", "mcp"), ("rag", "rag"), ("multi_agent", "multi-agent"))
REQUIRED_LINES = ("deployment", "endpoints", "ai services", "crud", "release recommendation", "human decision", "verdict")
NO_STATUS = "no response"            # how a check without an HTTP status code is quoted
RUN_CONCLUSIONS = ("success", "failure", "failed", "cancelled", "skipped", "timed_out", "neutral",
                   "action_required", "stale", "startup_failure")   # GitHub's words for how a run ended


def report_path() -> tuple[Path, bool]:
    """(path, is_sample). An explicit CLOUD_DEPLOYMENT_REPORT is never replaced by the sample."""
    if os.getenv("CLOUD_DEPLOYMENT_REPORT"):
        return Path(os.environ["CLOUD_DEPLOYMENT_REPORT"]), False
    if DEFAULT_REPORT.is_file():
        return DEFAULT_REPORT, False
    return SAMPLE_REPORT, True


def _state(value: Any) -> str:
    """enabled, disabled, or the report's own word; a state the report leaves out is unknown, never disabled."""
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    text = "" if value is None else str(value).strip().lower()
    if text in ("enabled", "on", "true", "1", "yes"):
        return "enabled"
    if text in ("disabled", "off", "false", "0", "no"):
        return "disabled"
    return text or "unknown"


def _flag(value: Any) -> bool | None:
    """A yes/no field read strictly: None when absent, and any text but true/yes/1 is False."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1")


def _code(value: Any) -> int | None:
    """An HTTP status code, or None when the value is not one (missing, true/false, text)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _checks(items: Any) -> list[dict[str, Any]]:
    """One entry per check. A check passes only when its status code equals the expected
    one and an "ok" field, if the report gives one, does not say otherwise."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        raw = item.get("status")
        status = _code(raw)
        expected = _code(item.get("expected_status", 200))
        ok = status is not None and status == expected and _flag(item.get("ok")) is not False
        if status is not None:
            status_text = str(status)
        elif raw is None or isinstance(raw, bool) or not str(raw).strip():
            status_text = NO_STATUS
        else:
            status_text = " ".join(str(raw).lower().split())
        out.append({"name": " ".join(str(item.get("name") or item.get("url") or "check").split()),
                    "method": str(item.get("method", "GET")).upper(), "url": str(item.get("url", "")),
                    "status": status_text, "expected_status": expected if expected is not None else item.get("expected_status"),
                    "ok": ok})
    return out


class CloudDeploymentReviewMode(Mode):
    key = "cloud_deployment_review"
    label = "Cloud Deployment Report Review"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=("Review the cloud deployment report and write the entry that supports the final "
                  "human release decision"),
            checks=[
                "the report names the provider, region, commit and the cloud-deployment.yml run",
                "every endpoint and CRUD check in the report returned its expected status",
                "AI-Mode, MCP, RAG and the Multi-Agent Server are all disabled in the baseline (the bonus profile may enable some)",
                "the entry quotes the provider, commit, counts, statuses and AI states exactly and records the human decision",
                "the release recommendation is approve only for a real deployment whose run succeeded, whose checks all "
                "passed, whose AI services match the profile and that has no open issue",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        path, is_sample = report_path()
        if not path.is_file():
            return Evidence(ok=False, summary=(
                f"cloud deployment report not found at {rel(path)}; the cloud owner's cloud-deployment.yml run "
                f"writes it (schema: docs/deployment/cloud-deployment-report-format.md), or set CLOUD_DEPLOYMENT_REPORT"))
        report = read_json(path)
        if not report:
            return Evidence(ok=False, summary=f"{rel(path)} is not a JSON object; see docs/deployment/cloud-deployment-report-format.md for the schema")
        is_sample = is_sample or _flag(report.get("sample")) is True        # the sample file, or a copy of it
        workflow = report.get("workflow") if isinstance(report.get("workflow"), dict) else {}
        run_id = str(workflow.get("run_id") or "").strip()
        run_id = "" if run_id == "0" else run_id                           # the sample's placeholder run
        conclusion = str(workflow.get("conclusion") or "").strip().lower()
        profile = "bonus" if str(report.get("profile") or "").strip().lower() == "bonus" else "baseline"
        resources = [r for r in (report.get("resources") or []) if isinstance(r, dict)]
        endpoints = _checks(report.get("endpoints"))
        crud = _checks(report.get("crud_checks"))
        ai_raw = report.get("ai_services") if isinstance(report.get("ai_services"), dict) else {}
        ai = {}
        for key, label in AI_SERVICES:
            value = ai_raw.get(key, ai_raw.get(label, ai_raw.get(key.replace("_", ""))))
            ai[label] = _state(value)
        issues = [str(i) for i in (report.get("issues") or [])]
        decision = report.get("release_decision") if isinstance(report.get("release_decision"), dict) else {}
        human = str(decision.get("decision", "")).strip().lower() or "pending"
        decided_by = str(decision.get("by", "")).strip()

        # Every reason to hold the release, in the words the entry and its rejection use.
        hold: list[str] = []
        if is_sample:
            hold.append("this is the sample report, not a real deployment")
        if not run_id:
            hold.append("the report names no cloud-deployment.yml run")
        elif conclusion != "success":
            hold.append(f"cloud-deployment.yml run {run_id} ended {conclusion or 'without a conclusion'}, not success")
        for label, items in (("endpoint", endpoints), ("CRUD", crud)):
            failed = [c for c in items if not c["ok"]]
            if not items:
                hold.append(f"the report has no {label} checks")
            elif failed:
                hold.append(f"{len(failed)} {label} check(s) failed: "
                            + ", ".join(f"{c['name']} {c['status']} (expected {c['expected_status']})" for c in failed))
        if profile == "baseline":
            not_off = [f"{label} {state}" for label, state in ai.items() if state != "disabled"]
            if not_off:
                hold.append("the baseline deployment must keep all four AI services disabled, but the report has "
                            + ", ".join(not_off))
        else:
            unknown = [f"{label} {state}" for label, state in ai.items() if state not in ("enabled", "disabled")]
            if unknown:
                hold.append("the report does not say whether these AI services are on: " + ", ".join(unknown))
        if issues:
            hold.append(f"{len(issues)} issue(s) are open")
        recommendation = "hold" if hold else "approve"

        facts = {
            "report": rel(path), "is_sample": is_sample, "profile": profile,
            "provider": str(report.get("provider", "")).lower(), "region": str(report.get("region", "")).lower(),
            "environment": str(report.get("environment", "")), "commit": str(report.get("commit", ""))[:7],
            "deployed_at": str(report.get("deployed_at", "")), "deployed_by": str(report.get("deployed_by", "")),
            "workflow_name": str(workflow.get("name", "")), "run_id": run_id, "run_url": str(workflow.get("run_url", "")),
            "workflow_conclusion": conclusion, "scripts": [str(s) for s in (report.get("scripts") or [])],
            "resources": resources, "endpoints": endpoints, "crud": crud, "ai_services": ai, "issues": issues,
            "endpoints_passed": sum(1 for c in endpoints if c["ok"]), "crud_passed": sum(1 for c in crud if c["ok"]),
            "recommendation": recommendation, "hold_reasons": hold, "human_decision": human, "decided_by": decided_by,
            "decision_note": str(decision.get("note", "")), "attention": recommendation != "approve",
        }
        ai_text = ", ".join(f"{label} {state}" for label, state in ai.items())
        checks = lambda items: ", ".join(f"{c['name']} {c['status']}" for c in items) or "none"  # noqa: E731
        return Evidence(
            ok=True,
            summary=(f"{facts['provider']} {facts['region']}, commit {facts['commit']}, "
                     + (f"run {run_id} {conclusion}" if run_id else "no cloud-deployment.yml run")
                     + f": {len(resources)} resources; "
                     f"endpoints {facts['endpoints_passed']}/{len(endpoints)} passed ({checks(endpoints)}); "
                     f"CRUD {facts['crud_passed']}/{len(crud)} passed ({checks(crud)}); {profile} profile, AI services {ai_text}; "
                     f"issues {len(issues)}; recommendation {recommendation}"
                     + (f" ({'; '.join(hold)})" if hold else "")
                     + f"; human decision {human}" + (f" by {decided_by}" if decided_by else "")).strip(),
            facts=facts,
            degraded=is_sample,
            note=("this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's "
                  "real report is not in the repo yet, so nothing here describes a real deployment and the release "
                  "is held" if is_sample else ""),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(PROMPT_FAMILY, "review_system.txt", "review_task.txt")
        f = evidence.facts
        lines = [
            f"Report: {f['report']}" + (" (SAMPLE, not a real deployment)" if f["is_sample"] else ""),
            f"Provider: {f['provider']}; region: {f['region']}; environment: {f['environment']}; commit: {f['commit']}; "
            f"deployed at {f['deployed_at']} by {f['deployed_by'] or 'unknown'}",
            (f"Workflow run: {f['run_id']} ({f['workflow_conclusion'] or 'no conclusion'}) {f['run_url']}".strip()
             if f["run_id"] else "Workflow run: none (the report names no cloud-deployment.yml run)"),
            f"Scripts: {', '.join(f['scripts']) or 'none listed'}",
            f"Resources ({len(f['resources'])}): " + (", ".join(
                f"{r.get('name', '?')} ({r.get('type', '?')}, {r.get('status', '?')})" for r in f["resources"]) or "none"),
            f"Endpoint checks ({f['endpoints_passed']}/{len(f['endpoints'])} passed):",
            *[f"- {c['name']}: {c['method']} {c['url']} -> {c['status']} (expected {c['expected_status']}) {'ok' if c['ok'] else 'FAILED'}"
              for c in f["endpoints"]],
            f"CRUD checks ({f['crud_passed']}/{len(f['crud'])} passed):",
            *[f"- {c['name']}: {c['method']} {c['url']} -> {c['status']} (expected {c['expected_status']}) {'ok' if c['ok'] else 'FAILED'}"
              for c in f["crud"]],
            f"Profile: {f['profile']} (the required deployment is the baseline, with all four AI services disabled)",
            "AI services: " + ", ".join(f"{label} {state}" for label, state in f["ai_services"].items()),
            f"Open issues: {'; '.join(f['issues']) if f['issues'] else 'none'}",
            f"Human release decision: {f['human_decision']}" + (f" by {f['decided_by']}" if f["decided_by"] else "")
            + (f" - {f['decision_note']}" if f["decision_note"] else ""),
            f"Required release recommendation: {f['recommendation']}"
            + (f" (hold because {'; '.join(f['hold_reasons'])})" if f["hold_reasons"] else ""),
            f"Required verdict word: {'ATTENTION' if f['attention'] else 'PASS'}",
        ]
        correction = ""
        if feedback:
            correction = (f"\n\nYour previous entry was rejected: {feedback}. Fix exactly that. Keep the seven-line "
                          "format and copy the provider, commit, counts, statuses and states from the evidence verbatim.")
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

        deployment = lines["deployment"].lower()
        if deployment:
            for word, what in ((f["provider"], "provider"), (f["region"], "region")):
                if word and word not in deployment:
                    reasons.append(f"the Deployment line must name the {what} {word}")
            if f["commit"] and f["commit"].lower() not in deployment:
                reasons.append(f"the Deployment line must quote the commit {f['commit']}")
            run = f["run_id"] or "none"
            if run not in deployment:
                reasons.append(f"the Deployment line must state the workflow run {run}")
            elif f["run_id"]:
                if f["workflow_conclusion"] and f["workflow_conclusion"] not in deployment:
                    reasons.append(f"the Deployment line must give run {run} its conclusion {f['workflow_conclusion']}")
            else:
                invented = re.search(r"workflow run none\s+(?:was\s+|is\s+)?([a-z_]+)", deployment)
                if invented and invented.group(1) in RUN_CONCLUSIONS:
                    reasons.append("the report names no cloud-deployment.yml run, so the Deployment line must read "
                                   f"'workflow run none' without a conclusion (it wrote {invented.group(1)})")
            if not re.search(rf"(?<!\d){len(f['resources'])}\s+resources?", deployment):
                reasons.append(f"the Deployment line must state {len(f['resources'])} resources")

        for label, key, passed_key in (("endpoints", "endpoints", "endpoints_passed"), ("crud", "crud", "crud_passed")):
            line = lines[label].lower()
            if not line:
                continue
            total = len(f[key])
            match = re.search(r"(\d+)\s*/\s*(\d+)\s+(?:checks\s+)?passed", line)
            if not match or match.groups() != (str(f[passed_key]), str(total)):
                reasons.append(f"the {label.capitalize()} line must state {f[passed_key]}/{total} checks passed")
            # Counted per (name, status), so two checks with one name and different results can both be quoted.
            wanted = Counter((c["name"].lower(), c["status"]) for c in f[key])
            shown = {c["name"].lower(): c["name"] for c in f[key]}
            for (name, status), count in wanted.items():
                if name not in line:
                    reasons.append(f"the {label.capitalize()} line must list the check '{shown[name]}' with its status {status}")
                elif len(re.findall(rf"{re.escape(name)}\D{{0,40}}?(?<!\d){re.escape(status)}(?!\d)", line)) < count:
                    reasons.append(f"the {label.capitalize()} line must give '{shown[name]}' its status {status}"
                                   + (f" ({count} checks have that name and status)" if count > 1 else ""))

        ai_line = lines["ai services"].lower()
        if ai_line:
            for label, state in f["ai_services"].items():
                match = re.search(rf"{re.escape(label)}\s+(enabled|disabled|[a-z]+)", ai_line)
                if not match:
                    reasons.append(f"the AI services line must state {label} {state}")
                elif match.group(1) != state:
                    reasons.append(f"the AI services line misquotes {label}: the report says {state}, not {match.group(1)}")

        rec_line = lines["release recommendation"].lower()
        if rec_line:
            words = re.findall(r"\b(approve|hold)\b", rec_line)
            if not words or words[0] != f["recommendation"]:
                why = ("the run succeeded, every endpoint and CRUD check passed, the AI services are as the profile "
                       "requires and no issue is open" if f["recommendation"] == "approve" else "; ".join(f["hold_reasons"]))
                reasons.append(f"the Release recommendation line must read {f['recommendation']}: {why}")

        human_line = lines["human decision"].lower()
        if human_line:
            if f["human_decision"] not in human_line:
                reasons.append(f"the Human decision line must state {f['human_decision']}")
            if f["decided_by"] and f["decided_by"].lower() not in human_line:
                reasons.append(f"the Human decision line must name who decided: {f['decided_by']}")

        verdict_line = lines["verdict"].lower()
        if verdict_line:
            expected_word = "attention" if f["attention"] else "pass"
            words = re.findall(r"\b(pass|attention)\b", verdict_line)
            if not words or words[0] != expected_word:
                reasons.append(f"the Verdict line must start with {expected_word.upper()} because the recommendation is {f['recommendation']}")
            if f["is_sample"] and "sample" not in verdict_line:
                reasons.append("the Verdict line must say this was the sample report, not a real deployment")

        return Verdict(ok=not reasons, reasons=reasons)
