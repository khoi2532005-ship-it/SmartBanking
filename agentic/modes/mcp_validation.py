"""Shared MCP server validation mode - Bao (Release 1).

Runs Lecture 7's test record against the team's shared MCP server, has the
model write the report entry, and checks that entry against the record.

ACT reuses `mcp_server/validate.py`: the same eight contract checks the
terminal script runs (reachable, tools/list, one valid call, three kinds of
invalid input, unknown tool, dependency down), so the loop and the script can
never disagree about what the contract is. OBSERVE rejects an entry that drops
a tool name, misquotes the demo call or its totals, skips one of the
rejections, or reports a pass count the record does not support; ADAPT retries
with that complaint. A server that is unreachable or fails a contract check
stops the run before any token is spent - it needs fixing, not a paragraph.

Env: MCP_SERVER_URL (default http://localhost:8100/mcp), the same name every
feature backend uses.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from importlib import metadata

from agentic import prompts
from agentic.core import Evidence, Mode, Plan, Verdict

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8100/mcp")
PROMPT_FAMILY = "_mcp"
START_HINT = "Start it with: python -m mcp_server.server"

# The report must say each of the five lines; a missing label is either a
# format slip or a truncated answer, and both need a retry.
REQUIRED_LINES = ("tools", "demo call", "result", "rejected", "verdict")

# How the entry may refer to each rejection check (record n -> accepted words,
# description used in the complaint when none of them appears).
REJECTION_WORDS = {
    4: (("month",), "the out-of-range month"),
    5: (("customer_id",), "the non-integer customer_id"),
    6: (("undeclared", "extra", "sql", "unexpected"), "the undeclared argument"),
    7: (("unknown tool", "no_such_tool"), "the unknown tool"),
}

_VERDICT_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*checks passed,\s*(\d+)\s*skipped")


def _has_number(line: str, value) -> bool:
    """`value` appears on `line` as a whole number token (commas ignored)."""
    return re.search(rf"(?<![\d.]){re.escape(str(value))}(?!\d)", line.replace(",", "")) is not None


def _money(value) -> str:
    return f"${float(value or 0):,.2f}"


def _tag(record: dict) -> str:
    return "SKIP" if record["skipped"] else ("PASS" if record["passed"] else "FAIL")


def _short(observed: str, limit: int = 80) -> str:
    """The server's own words for a rejection, without the transport prefixes."""
    text = observed
    for prefix in ("isError True: ", "isError true: ", "Error executing tool "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if ": " in text and text.split(": ", 1)[0].replace("_", "").isalnum():
        text = text.split(": ", 1)[1]          # "budgeting_summary: <message>"
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _line(output: str, label: str) -> str:
    """The output line that starts with `label:` (case-insensitive), or ''."""
    for line in output.splitlines():
        if line.strip().lower().startswith(label):
            return line.strip()
    return ""


class MCPValidationMode(Mode):
    key = "mcp_validation"
    label = "MCP Server Validation"
    owner = "Bao"

    def plan(self) -> Plan:
        return Plan(
            goal=(
                "Verify the shared MCP server honours its tool contracts, and that the "
                "model's test-record entry reports exactly what was observed"
            ),
            checks=[
                f"the MCP server answers initialize at {MCP_SERVER_URL}",
                "tools/list publishes every registered tool with an input schema",
                "a valid budgeting_summary call returns the declared structured result",
                "an out-of-range month, a non-integer customer_id and an undeclared argument "
                "are rejected before any backend call",
                "an unknown tool is rejected, never served; a tool whose service is down "
                "returns an explicit error, never invented data",
                "the entry names every tool, quotes the demo call and its totals, accounts "
                "for every rejection and matches the pass count",
            ],
            stop_condition="An entry passes OBSERVE, or the retry budget is spent.",
        )

    def collect(self) -> Evidence:
        try:
            from mcp_server import validate as mcp_validate
        except ImportError as exc:
            return Evidence(
                ok=False,
                summary=f"the MCP client SDK is not importable ({exc}). "
                        "Install it with: pip install -r requirements-agentic.txt",
            )

        records = [asdict(r) for r in mcp_validate.run_checks(MCP_SERVER_URL)]
        facts: dict = {"server_url": MCP_SERVER_URL, "records": records}

        if not records or not records[0]["passed"]:
            observed = records[0]["observed"] if records else "no result"
            return Evidence(ok=False, facts=facts,
                            summary=f"MCP server at {MCP_SERVER_URL}: {observed}. {START_HINT}")

        failed = [r for r in records if not r["passed"]]
        if failed:
            return Evidence(
                ok=False, facts=facts,
                summary="MCP contract check(s) failed: "
                        + "; ".join(f"{r['n']} {r['check']} - {r['observed']}" for r in failed)
                        + ". Fix that before asking for a report entry.",
            )

        by_n = {r["n"]: r for r in records}
        tool_specs = by_n[2]["detail"]                 # name -> {required, properties}
        valid = by_n[3]
        demo = valid["detail"]
        spending_source = demo.get("spending_source") or "unknown"
        rejections = [by_n[n] for n in REJECTION_WORDS if n in by_n]
        dependency = by_n.get(8)
        # A skipped check is not a pass: report passed / run, and skipped apart.
        skipped = [r["n"] for r in records if r["skipped"]]
        passed_count = sum(1 for r in records if r["passed"] and not r["skipped"])
        run_count = len(records) - len(skipped)

        try:
            sdk_version = metadata.version("mcp")
        except metadata.PackageNotFoundError:
            sdk_version = "unknown"

        # Mock spending means the Transactions API was down and the budgets
        # backend fell back. The contract checks are unaffected, but the totals
        # in the entry are not live cross-feature data, so say so.
        degraded = spending_source != "transactions-api"

        facts.update({
            "mcp_sdk_version": sdk_version,
            "tools": list(tool_specs),
            "tool_specs": tool_specs,
            "tool_count": len(tool_specs),
            "demo_call": {"tool": valid["tool"], "arguments": valid["arguments"]},
            "demo_result": {
                "budget_count": demo.get("budget_count"),
                "total_spent": demo.get("total_spent"),
                "total_limit": demo.get("total_limit"),
                "spending_source": spending_source,
            },
            "rejections": [
                {"n": r["n"], "check": r["check"], "tool": r["tool"],
                 "arguments": r["arguments"], "observed": r["observed"]}
                for r in rejections
            ],
            "dependency_check": (
                {"skipped": dependency["skipped"], "tool": dependency["tool"],
                 "observed": dependency["observed"]} if dependency else None
            ),
            "passed_count": passed_count,
            "run_count": run_count,
            "skipped_count": len(skipped),
            "total": len(records),
            "skipped": skipped,
        })

        # The summary doubles as the evidence the REVIEW stage judges the entry
        # against, so it carries the names and figures the entry must quote.
        rejected = "; ".join(
            f"{json.dumps(r['arguments']) if r['tool'] != 'no_such_tool' else r['tool']} -> "
            f"{_short(r['observed'])}"
            for r in rejections
        )
        return Evidence(
            ok=True,
            summary=(
                f"{len(tool_specs)} tools on {MCP_SERVER_URL}: {', '.join(tool_specs)}. "
                f"Valid call {valid['tool']} {json.dumps(valid['arguments'])} -> "
                f"{demo.get('budget_count')} budgets, total spent {_money(demo.get('total_spent'))} of "
                f"{_money(demo.get('total_limit'))}, spending source {spending_source}. "
                f"Rejected: {rejected}. "
                f"{passed_count}/{run_count} checks passed, {len(skipped)} skipped"
            ),
            facts=facts,
            degraded=degraded,
            note=(
                "the valid call's totals come from mock spending (Transactions API unreachable); "
                "the contract checks themselves are unaffected"
                if degraded else ""
            ),
        )

    def build_prompt(self, plan: Plan, evidence: Evidence, feedback: str) -> tuple[str, str]:
        system_prompt, task_prompt = prompts.load_all(
            PROMPT_FAMILY, "validation_system.txt", "validation_task.txt",
        )
        f = evidence.facts
        demo = f["demo_result"]

        tool_lines = [
            f"- {name} (requires: {', '.join(spec.get('required') or []) or 'none'})"
            for name, spec in f["tool_specs"].items()
        ]
        check_lines = [
            f"{r['n']}. {r['check']}"
            + (f" [{r['tool']} {json.dumps(r['arguments'])}]" if r["arguments"] else "")
            + f": {_tag(r)} - {r['observed']}"
            for r in f["records"]
        ]
        skipped_note = (
            f" (check {', '.join(map(str, f['skipped']))} skipped - not run, not counted as passed; see its observed line)"
            if f["skipped"] else ""
        )

        evidence_block = "\n".join([
            f"Server: {f['server_url']} (mcp SDK {f['mcp_sdk_version']})",
            f"Registered tools ({f['tool_count']}):",
            *tool_lines,
            "Checks:",
            *check_lines,
            f"Demo call: {f['demo_call']['tool']} with {json.dumps(f['demo_call']['arguments'])}",
            f"Demo result: total spent {_money(demo['total_spent'])} of {_money(demo['total_limit'])} "
            f"across {demo['budget_count']} budgets; spending source {demo['spending_source']}",
            f"Checks passed: {f['passed_count']}/{f['run_count']}, {f['skipped_count']} skipped{skipped_note}",
        ])

        # The Adapt stage, concretely: the previous verdict's complaint becomes
        # a correction the model has to satisfy this time.
        correction = ""
        if feedback:
            correction = (
                f"\n\nYour previous entry was rejected: {feedback}. Fix exactly that. Keep the "
                "five-line format and copy tool names, argument values and figures from the "
                "evidence verbatim."
            )

        return system_prompt, f"{task_prompt}{correction}\n\nEvidence:\n{evidence_block}"

    def validate(self, output: str, evidence: Evidence) -> Verdict:
        """Every figure is checked on the line that is supposed to carry it, so a
        number that merely appears somewhere in the text does not count."""
        f = evidence.facts
        reasons: list[str] = []

        if not output.strip():
            return Verdict(False, ["the entry was empty"])

        lines = {label: _line(output, label) for label in REQUIRED_LINES}
        for label, line in lines.items():
            if not line:
                reasons.append(f"it did not include the '{label.capitalize()}:' line")

        # Tools line: the count as a number and every registered tool by name.
        tools_line = lines["tools"].lower()
        if tools_line:
            if not _has_number(tools_line, f["tool_count"]):
                reasons.append(f"the Tools line did not state the tool count ({f['tool_count']}) as a number")
            missing = [name for name in f["tools"] if name.lower() not in tools_line]
            if missing:
                reasons.append("the Tools line did not name these registered tools: " + ", ".join(missing))

        # Demo call line: the right tool and every argument with its value.
        call = f["demo_call"]
        demo_line = lines["demo call"].lower()
        if demo_line:
            if call["tool"].lower() not in demo_line:
                reasons.append(f"the Demo call line did not name the tool {call['tool']}")
            for key, value in call["arguments"].items():
                if key.lower() not in demo_line or not _has_number(demo_line, value):
                    reasons.append(f"the Demo call line did not include the argument {key}={json.dumps(value)}")

        # Result line: the totals from the structured result, and the spending source.
        result_line = lines["result"].lower()
        demo = f["demo_result"]
        if result_line:
            spent = demo.get("total_spent")
            if spent is not None:
                whole, rounded = int(float(spent)), int(round(float(spent)))
                if not (_has_number(result_line, whole) or _has_number(result_line, rounded)):
                    reasons.append(f"the Result line did not state the total spent ({_money(spent)}) as a number")
            count = demo.get("budget_count")
            if count is not None and not _has_number(result_line, count):
                reasons.append(f"the Result line did not state the budget count ({count}) as a number")
            if str(demo.get("spending_source", "")).lower() not in result_line:
                reasons.append(f"the Result line did not state the spending source ({demo.get('spending_source')})")

        # Rejected line: every rejection accounted for.
        rejected_line = lines["rejected"].lower()
        if rejected_line:
            for r in f["rejections"]:
                words, description = REJECTION_WORDS[r["n"]]
                if not any(w in rejected_line for w in words):
                    reasons.append(f"the Rejected line did not mention that {description} was rejected")

        # Verdict line: passed / run, skipped apart, and the closing word.
        verdict_line = lines["verdict"].lower()
        expected = f"{f['passed_count']}/{f['run_count']} checks passed, {f['skipped_count']} skipped"
        if verdict_line:
            match = _VERDICT_RE.search(verdict_line)
            if not match or match.groups() != (str(f["passed_count"]), str(f["run_count"]), str(f["skipped_count"])):
                reasons.append(
                    f"the Verdict line must read '{expected}' - a skipped check is not a pass"
                )
            all_passed = f["passed_count"] == f["run_count"]
            words = re.findall(r"\b(pass|fail)\b", verdict_line)
            final = words[-1] if words else ""
            if all_passed and final != "pass":
                reasons.append("the Verdict line must end with PASS because every check that ran passed")
            if not all_passed and final != "fail":
                reasons.append("the Verdict line must end with FAIL because a check failed")

        return Verdict(ok=not reasons, reasons=reasons)
