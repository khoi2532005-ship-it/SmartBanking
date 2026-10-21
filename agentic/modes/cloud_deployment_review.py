"""Cloud Deployment Report Review mode - Bao (Release 2).

Reviews the cloud deployment report the cloud owner produces and has the model
write the Cloud Deployment Review entry that supports the final human release
decision.

ACT reads one JSON report (schema in docs/deployment/README.md): provider and
region, the commit and workflow run, the resources, the endpoint and CRUD
checks with their status codes, the state of the four AI services (disabled by
default in the required cloud deployment), open issues, and the human release
decision once it has been made. OBSERVE rejects an entry that misquotes the
provider, the commit, a count, a status, an AI service's state, the human
decision, or that recommends approval when a check failed; ADAPT retries with
that complaint. Until the real report exists the sample report is reviewed
and the run is marked degraded, so the mode can be demonstrated before the
cloud deployment lands.

Env: CLOUD_DEPLOYMENT_REPORT (default docs/deployment/cloud-deployment-report.json;
falls back to cloud-deployment-report.sample.json next to it).
"""

from __future__ import annotations

import os
import re
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


def report_path() -> tuple[Path, bool]:
    """(path, is_sample). An explicit CLOUD_DEPLOYMENT_REPORT is never replaced by the sample."""
    if os.getenv("CLOUD_DEPLOYMENT_REPORT"):
        return Path(os.environ["CLOUD_DEPLOYMENT_REPORT"]), False
    if DEFAULT_REPORT.is_file():
        return DEFAULT_REPORT, False
    return SAMPLE_REPORT, True


def _state(value: Any) -> str:
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    text = str(value or "").strip().lower()
    if text in ("enabled", "on", "true", "1", "yes"):
        return "enabled"
    if text in ("disabled", "off", "false", "0", "no", ""):
        return "disabled"
    return text


def _checks(items: Any) -> list[dict[str, Any]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        expected = item.get("expected_status", 200)
        ok = item.get("ok")
        if ok is None:
            try:
                ok = int(status) == int(expected)
            except (TypeError, ValueError):
                ok = False
        out.append({"name": str(item.get("name") or item.get("url") or "check").strip(),
                    "method": str(item.get("method", "GET")).upper(), "url": str(item.get("url", "")),
                    "status": status, "expected_status": expected, "ok": bool(ok)})
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
                "AI-Mode, MCP, RAG and the Multi-Agent Server states are reported as the baseline requires (disabled by default)",
                "the entry quotes the provider, commit, counts, statuses and AI states exactly and records the human decision",
                "the release recommendation is approve only when every check passed and no issue is open",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        path, is_sample = report_path()
        if not path.is_file():
            return Evidence(ok=False, summary=(
                f"cloud deployment report not found at {rel(path)}; the cloud owner's cloud-deployment.yml run "
                f"writes it (schema: docs/deployment/README.md), or set CLOUD_DEPLOYMENT_REPORT"))
        report = read_json(path)
        if not report:
            return Evidence(ok=False, summary=f"{rel(path)} is not a JSON object; see docs/deployment/README.md for the schema")
        workflow = report.get("workflow") or {}
        resources = [r for r in (report.get("resources") or []) if isinstance(r, dict)]
        endpoints = _checks(report.get("endpoints"))
        crud = _checks(report.get("crud_checks"))
        ai_raw = report.get("ai_services") or {}
        ai = {}
        for key, label in AI_SERVICES:
            value = ai_raw.get(key, ai_raw.get(label, ai_raw.get(key.replace("_", ""))))
            ai[label] = _state(value)
        issues = [str(i) for i in (report.get("issues") or [])]
        decision = report.get("release_decision") or {}
        human = str(decision.get("decision", "")).strip().lower() or "pending"
        decided_by = str(decision.get("by", "")).strip()
        all_ok = all(c["ok"] for c in endpoints) and all(c["ok"] for c in crud) and bool(endpoints) and bool(crud)
        workflow_ok = str(workflow.get("conclusion", "success")).lower() in ("success", "")
        recommendation = "approve" if all_ok and workflow_ok and not issues else "hold"
        facts = {
            "report": rel(path), "is_sample": is_sample,
            "provider": str(report.get("provider", "")).lower(), "region": str(report.get("region", "")).lower(),
            "environment": str(report.get("environment", "")), "commit": str(report.get("commit", ""))[:7],
            "deployed_at": str(report.get("deployed_at", "")), "deployed_by": str(report.get("deployed_by", "")),
            "run_id": str(workflow.get("run_id", "")), "run_url": str(workflow.get("run_url", "")),
            "workflow_conclusion": str(workflow.get("conclusion", "")), "scripts": [str(s) for s in (report.get("scripts") or [])],
            "resources": resources, "endpoints": endpoints, "crud": crud, "ai_services": ai, "issues": issues,
            "endpoints_passed": sum(1 for c in endpoints if c["ok"]), "crud_passed": sum(1 for c in crud if c["ok"]),
            "recommendation": recommendation, "human_decision": human, "decided_by": decided_by,
            "decision_note": str(decision.get("note", "")), "attention": recommendation != "approve",
        }
        ai_text = ", ".join(f"{label} {state}" for label, state in ai.items())
        checks = lambda items: ", ".join(f"{c['name']} {c['status']}" for c in items) or "none"  # noqa: E731
        return Evidence(
            ok=True,
            summary=(f"{facts['provider']} {facts['region']}, commit {facts['commit']}, run {facts['run_id'] or 'none'} "
                     f"{facts['workflow_conclusion'] or ''}: {len(resources)} resources; "
                     f"endpoints {facts['endpoints_passed']}/{len(endpoints)} passed ({checks(endpoints)}); "
                     f"CRUD {facts['crud_passed']}/{len(crud)} passed ({checks(crud)}); AI services {ai_text}; "
                     f"issues {len(issues)}; recommendation {recommendation}; human decision {human}"
                     + (f" by {decided_by}" if decided_by else "")).strip(),
            facts=facts,
            degraded=is_sample,
            note=("this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's "
                  "real report is not in the repo yet, so nothing here describes a real deployment" if is_sample else ""),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(PROMPT_FAMILY, "review_system.txt", "review_task.txt")
        f = evidence.facts
        lines = [
            f"Report: {f['report']}" + (" (SAMPLE, not a real deployment)" if f["is_sample"] else ""),
            f"Provider: {f['provider']}; region: {f['region']}; environment: {f['environment']}; commit: {f['commit']}; "
            f"deployed at {f['deployed_at']} by {f['deployed_by'] or 'unknown'}",
            f"Workflow run: {f['run_id'] or 'none'} ({f['workflow_conclusion'] or 'no conclusion'}) {f['run_url']}".strip(),
            f"Scripts: {', '.join(f['scripts']) or 'none listed'}",
            f"Resources ({len(f['resources'])}): " + (", ".join(
                f"{r.get('name', '?')} ({r.get('type', '?')}, {r.get('status', '?')})" for r in f["resources"]) or "none"),
            f"Endpoint checks ({f['endpoints_passed']}/{len(f['endpoints'])} passed):",
            *[f"- {c['name']}: {c['method']} {c['url']} -> {c['status']} (expected {c['expected_status']}) {'ok' if c['ok'] else 'FAILED'}"
              for c in f["endpoints"]],
            f"CRUD checks ({f['crud_passed']}/{len(f['crud'])} passed):",
            *[f"- {c['name']}: {c['method']} {c['url']} -> {c['status']} (expected {c['expected_status']}) {'ok' if c['ok'] else 'FAILED'}"
              for c in f["crud"]],
            "AI services: " + ", ".join(f"{label} {state}" for label, state in f["ai_services"].items()),
            f"Open issues: {'; '.join(f['issues']) if f['issues'] else 'none'}",
            f"Human release decision: {f['human_decision']}" + (f" by {f['decided_by']}" if f["decided_by"] else "")
            + (f" - {f['decision_note']}" if f["decision_note"] else ""),
            f"Required release recommendation: {f['recommendation']}",
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
            for c in f[key]:
                name = c["name"].lower()
                if name not in line:
                    reasons.append(f"the {label.capitalize()} line must list the check '{c['name']}' with its status {c['status']}")
                elif not re.search(rf"{re.escape(name)}\D{{0,40}}?(?<!\d){re.escape(str(c['status']))}(?!\d)", line):
                    reasons.append(f"the {label.capitalize()} line must give '{c['name']}' its status {c['status']}")

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
                why = ("every endpoint and CRUD check passed and no issue is open" if f["recommendation"] == "approve"
                       else f"{len(f['endpoints']) - f['endpoints_passed']} endpoint and {len(f['crud']) - f['crud_passed']} CRUD "
                            f"check(s) failed or {len(f['issues'])} issue(s) are open")
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
