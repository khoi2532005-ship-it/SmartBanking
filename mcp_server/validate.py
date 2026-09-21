"""Terminal validation of the shared MCP server - Lecture 7's Test Record.

    python -m mcp_server.validate                 # print the test record
    python -m mcp_server.validate --evidence      # also save docs/evidence/mcp-validation-<ts>.json
    python -m mcp_server.validate --url http://localhost:8100/mcp

One tool, several test paths, each recorded as tool + arguments + expected +
observed + result. Pass rule: observed behaviour matches the tool contract.

    1  reachable            initialize succeeds
    2  tools/list           every registered tool is published with a schema
    3  valid invocation     budgeting_summary returns the declared structure
    4  domain-invalid       month=13 is rejected before the backend is called
    5  type-invalid         customer_id="abc" is rejected by the schema
    6  unknown argument     an undeclared `sql` argument is rejected
    7  unknown tool         tools/call on a missing tool is rejected, not served
    8  dependency down      a tool whose feature service is off returns
                            isError, never an invented result

Exit code 0 when every check passes, 1 otherwise, so it can gate a script.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp_server import client, config
from mcp_server.tools import tool_names

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"

VALID_ARGS = {"customer_id": 1, "month": 9, "year": 2026}


@dataclass
class Record:
    n: int
    check: str
    tool: str
    arguments: dict[str, Any]
    expected: str
    observed: str = ""
    passed: bool = False
    skipped: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def _service_up(url: str) -> bool:
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def run_checks(url: str) -> list[Record]:
    records: list[Record] = []

    # 1 - reachable -------------------------------------------------------
    rec = Record(1, "server reachable", "-", {}, "initialize succeeds")
    try:
        client.ping(url)
        rec.observed, rec.passed = "initialize ok", True
    except client.MCPUnreachable as exc:
        rec.observed = str(exc)
        records.append(rec)
        return records  # nothing else can run
    records.append(rec)

    # 2 - tools/list ------------------------------------------------------
    expected_tools = tool_names()
    rec = Record(2, "tools/list publishes every tool", "-", {},
                 f"{len(expected_tools)} tools, each with an inputSchema")
    tools = client.list_tools(url)
    listed = {t.name: t for t in tools}
    missing = [n for n in expected_tools if n not in listed]
    no_schema = [n for n, t in listed.items() if not t.input_schema.get("properties")]
    rec.observed = f"{len(tools)} tools: {', '.join(listed)}" + (
        f"; missing {missing}" if missing else "") + (
        f"; no schema on {no_schema}" if no_schema else "")
    rec.passed = not missing and not no_schema
    rec.detail = {
        name: {"required": t.input_schema.get("required", []),
               "properties": list(t.input_schema.get("properties", {}))}
        for name, t in listed.items()
    }
    records.append(rec)

    # 3 - valid invocation -----------------------------------------------
    rec = Record(3, "valid invocation", "budgeting_summary", dict(VALID_ARGS),
                 "isError false; structured result with totals and budgets")
    res = client.call_tool("budgeting_summary", VALID_ARGS, url)
    if res.is_error:
        rec.observed = f"isError true: {res.text[:160]}"
        if "unavailable" in res.text.lower():
            rec.observed += "  (start budgeting-service on 5004 and re-run)"
    else:
        s = res.structured or {}
        ok = isinstance(s.get("totals"), dict) and isinstance(s.get("budgets"), list)
        rec.observed = (
            f"isError false; budget_count={s.get('budget_count')}, "
            f"total_spent={s.get('totals', {}).get('total_spent')}, "
            f"spending_source={s.get('spending_source')}"
        )
        rec.passed = ok and s.get("budget_count", 0) > 0
        rec.detail = {"structured_keys": sorted(s.keys())}
    records.append(rec)

    # 4 - domain-invalid ---------------------------------------------------
    args = {**VALID_ARGS, "month": 13}
    rec = Record(4, "domain-invalid input rejected", "budgeting_summary", args,
                 "isError true mentioning month; backend not called")
    res = client.call_tool("budgeting_summary", args, url)
    rec.observed = f"isError {res.is_error}: {res.text[:120]}"
    rec.passed = res.is_error and "month" in res.text.lower()
    records.append(rec)

    # 5 - type-invalid ---------------------------------------------------
    args = {**VALID_ARGS, "customer_id": "abc"}
    rec = Record(5, "type-invalid input rejected", "budgeting_summary", args,
                 "isError true from schema validation")
    res = client.call_tool("budgeting_summary", args, url)
    rec.observed = f"isError {res.is_error}: {res.text[:120].replace(chr(10), ' ')}"
    rec.passed = res.is_error and "customer_id" in res.text
    records.append(rec)

    # 6 - unknown argument --------------------------------------------------
    args = {**VALID_ARGS, "sql": "SELECT * FROM budgets"}
    rec = Record(6, "undeclared argument rejected", "budgeting_summary", args,
                 "isError true: extra inputs not permitted")
    res = client.call_tool("budgeting_summary", args, url)
    rec.observed = f"isError {res.is_error}: {res.text[:120].replace(chr(10), ' ')}"
    rec.passed = res.is_error and "extra" in res.text.lower()
    records.append(rec)

    # 7 - unknown tool ----------------------------------------------------
    rec = Record(7, "unknown tool rejected", "no_such_tool", {},
                 "JSON-RPC error, or isError true naming the unknown tool; never a result")
    try:
        res = client.call_tool("no_such_tool", {}, url)
        rec.observed = f"isError {res.is_error}: {res.text[:100]}"
        # FastMCP 1.x answers with a tool error rather than a JSON-RPC error;
        # both are explicit rejections with no fabricated result.
        rec.passed = res.is_error and "unknown tool" in res.text.lower()
    except client.MCPProtocolError as exc:
        rec.observed, rec.passed = f"MCPProtocolError: {str(exc)[:100]}", True
    records.append(rec)

    # 8 - dependency unavailable -----------------------------------------
    probes = {
        "loans_list": ("loans", {"customer_id": 1}),
        "fraud_alerts_count": ("fraud", {}),
        "accounts_count": ("accounts", {}),
        "transactions_spending": ("transactions", dict(VALID_ARGS)),
    }
    down = [(t, f, a) for t, (f, a) in probes.items()
            if not _service_up(config.SERVICE_URLS[f])]
    if down:
        tool, feature, args = down[0]
        rec = Record(8, "dependency unavailable -> explicit error", tool, args,
                     "isError true saying the service is unavailable; no fabricated data")
        res = client.call_tool(tool, args, url)
        rec.observed = f"isError {res.is_error}: {res.text[:120]}"
        rec.passed = res.is_error and "unavailable" in res.text.lower()
    else:
        rec = Record(8, "dependency unavailable -> explicit error", "-", {},
                     "isError true when a feature service is down",
                     observed="skipped - every feature service is running", skipped=True,
                     passed=True)
    records.append(rec)

    return records


def print_report(url: str, records: list[Record]) -> None:
    rule = "=" * 72
    print(rule)
    print("  SmartBank MCP server - terminal validation")
    print(f"  server:  {url}")
    print(f"  mcp sdk: {metadata.version('mcp')}   commit: {_git_sha()}")
    print(rule)
    for r in records:
        tag = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
        print(f"  {tag}  {r.n}. {r.check}")
        print(f"        tool:      {r.tool}  {json.dumps(r.arguments) if r.arguments else ''}")
        print(f"        expected:  {r.expected}")
        print(f"        observed:  {r.observed}")
    passed = sum(1 for r in records if r.passed)
    print(rule)
    print(f"  {passed}/{len(records)} checks passed")
    print(rule)


def write_evidence(url: str, records: list[Record]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "kind": "mcp-terminal-validation",
        "timestamp": stamp,
        "server_url": url,
        "mcp_sdk_version": metadata.version("mcp"),
        "implementation_version": _git_sha(),
        "records": [asdict(r) for r in records],
        "passed": all(r.passed for r in records),
    }
    path = EVIDENCE_DIR / f"mcp-validation-{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the shared MCP server.")
    parser.add_argument("--url", default=client.DEFAULT_URL)
    parser.add_argument("--evidence", action="store_true",
                        help="write docs/evidence/mcp-validation-<timestamp>.json")
    args = parser.parse_args(argv)

    records = run_checks(args.url)
    print_report(args.url, records)
    if args.evidence:
        path = write_evidence(args.url, records)
        print(f"  evidence: {path.relative_to(REPO_ROOT)}")
    return 0 if all(r.passed for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
