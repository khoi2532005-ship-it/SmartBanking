"""Terminal runner: start one workflow, follow it stage by stage, decide, read the response.

    python -m multi_agent_server.run --feature budgeting --customer 1 --month 9 --year 2026 \\
        --request "Which budget categories went over the limit and by how much?"

The same flow the app drives (POST /workflow, poll /status, POST /decision,
GET /response), from a terminal. With --decision the prompt is skipped.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from typing import Any, Callable

from multi_agent_server import config, terminal
from multi_agent_server.models import DECISIONS, State


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m multi_agent_server.run",
                                     description="Run one multi-agent workflow from the terminal.")
    parser.add_argument("--feature", choices=list(config.FEATURES), default="budgeting")
    parser.add_argument("--request", required=True, help="what to ask, in plain English (max 1000 chars)")
    parser.add_argument("--customer", type=int, default=1)
    parser.add_argument("--month", type=int, default=date.today().month)
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--url", default=None, help="server URL (default: MULTI_AGENT_HOST/PORT from .env)")
    parser.add_argument("--decision", choices=list(DECISIONS), default=None, help="decide without prompting")
    parser.add_argument("--note", default="", help="correction note to record with --decision")
    parser.add_argument("--by", default="terminal")
    parser.add_argument("--timeout", type=terminal.positive_float, default=300,
                        help="seconds to wait for the human-review stage")
    parser.add_argument("--poll", type=terminal.positive_float, default=1.0, help="seconds between status polls")
    return parser


def follow(client: Any, workflow_id: str, timeout: float, poll: float, out: Callable[[str], None],
           sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Poll the status, printing each stage as it finishes, until the gate or a failure."""
    seen = 0
    deadline = time.monotonic() + timeout
    while True:
        status, body = client.get(f"/workflow/{workflow_id}/status")
        if status != 200:
            raise terminal.ServerUnavailable(f"status check failed ({status}): {body.get('error')}")
        for stage in body["stages"][seen:]:
            if stage["status"] == "running":
                break
            flag = " (fallback)" if stage["fallback"] else ""
            out(f"  {stage['role']:<8} attempt {stage['attempt']}  {stage['status']}{flag}  "
                f"{stage['duration_seconds']}s  {stage['model']}")
            seen += 1
        if body["state"] in (State.AWAITING_HUMAN_REVIEW, *State.TERMINAL):
            return body
        if time.monotonic() > deadline:
            raise terminal.ServerUnavailable(f"workflow {workflow_id} still {body['state']} after {timeout:g}s")
        sleep(poll)


def main(argv: list[str] | None = None, *, client: Any | None = None,
         input_fn: Callable[[str], str] = input, out: Callable[[str], None] = terminal.stdout,
         sleep: Callable[[float], None] = time.sleep) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    terminal.require_note_for_partial(parser, args)
    terminal.configure_console()
    client = client or terminal.HttpClient(args.url)
    try:
        status, body = client.post("/workflow", {
            "feature": args.feature, "request": args.request,
            "context": {"customer_id": args.customer, "month": args.month, "year": args.year},
        })
        if status != 202:
            return terminal.fail(f"server refused the request ({status}): {body.get('error')}", out)
        workflow_id = body["workflow_id"]
        out(f"Started {workflow_id} ({args.feature}) at {client.base_url}; following the stages:")
        final = follow(client, workflow_id, args.timeout, args.poll, out, sleep)
        status, full = client.get(f"/workflow/{workflow_id}")
        if status != 200:
            return terminal.fail(f"could not read {workflow_id} ({status}): {full.get('error')}", out)
        out("")
        out(terminal.render_workflow(full))
        if final["state"] == State.FAILED:
            out(f"  workflow failed: {final['error']}")
            return 2
        if final["state"] != State.AWAITING_HUMAN_REVIEW:
            out(f"  workflow is {final['state']}; nothing to decide.")
            return 0
        out("")
        out("  Awaiting your decision. The response is not released until you decide.")
        if args.decision:
            decision, note = args.decision, args.note
        else:
            decision, note = terminal.prompt_decision(input_fn, out)
            if decision is None:
                out(f"  left in awaiting_human_review; decide later with: python -m multi_agent_server.review --id {workflow_id}")
                return 0
        status, decided = terminal.send_decision(client, workflow_id, decision, note, args.by)
        if status != 200:
            return terminal.fail(f"decision rejected ({status}): {decided.get('error')}", out)
        status, response = client.get(f"/workflow/{workflow_id}/response")
        if status != 200:
            return terminal.fail(f"could not read the response ({status}): {response.get('error')}", out)
        out("")
        out(terminal.render_response(response))
        return 0
    except terminal.InputClosed as exc:
        out(f"  stopped: {exc}; decide later with: python -m multi_agent_server.review --id {workflow_id}")
        return 0
    except terminal.ServerUnavailable as exc:
        return terminal.fail(str(exc), out)
    except KeyboardInterrupt:
        out("\nstopped")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
