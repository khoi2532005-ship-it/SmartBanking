"""Terminal human review: decide on workflows waiting in awaiting_human_review.

    python -m multi_agent_server.review                      # prompt for each pending workflow
    python -m multi_agent_server.review --watch 5            # keep polling every 5 s (demo mode)
    python -m multi_agent_server.review --id wf_1234abcd --decision accept --note "ok"

Each decision goes to POST /workflow/<id>/decision, the same endpoint the UI
uses, so the audit shows who decided (by: terminal) and the response is only
released after this step.

Exit codes: 0 when every decision asked for was recorded (or there was nothing
to decide), 1 when a decision was refused or a workflow could not be read,
2 for bad arguments, 130 on Ctrl+C.
"""

from __future__ import annotations

import argparse
import time
from typing import Any, Callable

from multi_agent_server import terminal
from multi_agent_server.models import DECISIONS, State

DECIDED, SKIPPED, NOTHING, REFUSED, UNREADABLE = "decided", "skipped", "nothing", "refused", "unreadable"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m multi_agent_server.review",
                                     description="Human review of pending multi-agent workflows.")
    parser.add_argument("--url", default=None, help="server URL (default: MULTI_AGENT_HOST/PORT from .env)")
    parser.add_argument("--id", dest="workflow_id", default=None, help="review one workflow only")
    parser.add_argument("--decision", choices=list(DECISIONS), default=None,
                        help="decide without prompting (use with --id or for every pending workflow)")
    parser.add_argument("--note", default="", help="correction note to record with --decision")
    parser.add_argument("--by", default="terminal", help="who is deciding, recorded in the audit")
    parser.add_argument("--watch", type=terminal.positive_float, default=None, metavar="SECONDS",
                        help="keep polling for new pending workflows every SECONDS")
    return parser


def review_one(client: Any, workflow_id: str, args: argparse.Namespace, input_fn: Callable[[str], str],
               out: Callable[[str], None]) -> str:
    """Show one workflow and record a decision. Returns one of the outcome constants."""
    status, full = client.get(f"/workflow/{workflow_id}")
    if status != 200:
        out(f"  {workflow_id}: {full.get('error', status)}")
        return UNREADABLE
    out("")
    out(terminal.render_workflow(full))
    if full["state"] != State.AWAITING_HUMAN_REVIEW:
        out(f"  {workflow_id} is {full['state']}; nothing to decide.")
        return NOTHING
    if args.decision:
        decision, note = args.decision, args.note
    else:
        decision, note = terminal.prompt_decision(input_fn, out)
        if decision is None:
            out("  skipped")
            return SKIPPED
    status, body = terminal.send_decision(client, workflow_id, decision, note, args.by)
    if status != 200:
        out(f"  decision refused ({status}): {body.get('error')}")
        return REFUSED
    out(f"  -> {body['state']}" + ("; response released" if body["released"] else "; response withheld"))
    out(terminal.render_response(body["final_response"]))
    return DECIDED


def pass_once(client: Any, args: argparse.Namespace, input_fn: Callable[[str], str], out: Callable[[str], None],
              seen: dict[str, str] | None = None, header: list[int] | None = None) -> int:
    """One pass over the pending list (or the one --id). 0 unless something was refused or unreadable."""
    if args.workflow_id:
        outcome = review_one(client, args.workflow_id, args, input_fn, out)
        return 1 if outcome in (REFUSED, UNREADABLE) else 0
    status, pending = client.get("/workflows/pending")
    if status != 200:
        return terminal.fail(f"server answered {status}: {pending.get('error')}", out)
    if header is None or header[-1:] != [pending["count"]]:
        out(f"Multi-Agent Server at {client.base_url} - {pending['count']} workflow(s) awaiting human review")
        if header is not None:
            header.append(pending["count"])
    code = 0
    for item in pending["workflows"]:
        if seen is not None and seen.get(item["workflow_id"]) == item["updated_at"]:
            continue                                       # skipped earlier and unchanged since
        outcome = review_one(client, item["workflow_id"], args, input_fn, out)
        if outcome in (REFUSED, UNREADABLE):
            code = 1
        if outcome == SKIPPED and seen is not None:
            seen[item["workflow_id"]] = item["updated_at"]
    return code


def watch_one(client: Any, args: argparse.Namespace, input_fn: Callable[[str], str],
              out: Callable[[str], None], sleep: Callable[[float], None] = time.sleep) -> int:
    """Wait for one workflow to reach the gate, decide, then stop."""
    announced = False
    while True:
        status, body = client.get(f"/workflow/{args.workflow_id}/status")
        if status != 200:
            return terminal.fail(f"{args.workflow_id}: {body.get('error', status)}", out)
        if body["state"] == State.AWAITING_HUMAN_REVIEW:
            outcome = review_one(client, args.workflow_id, args, input_fn, out)
            return 1 if outcome in (REFUSED, UNREADABLE) else 0
        if body["state"] in State.TERMINAL:
            out(f"  {args.workflow_id} is {body['state']}; nothing to decide.")
            return 0
        if not announced:
            out(f"  {args.workflow_id} is {body['state']}; waiting for the human gate...")
            announced = True
        sleep(args.watch)


def main(argv: list[str] | None = None, *, client: Any | None = None,
         input_fn: Callable[[str], str] = input, out: Callable[[str], None] = terminal.stdout,
         sleep: Callable[[float], None] = time.sleep) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    terminal.require_note_for_partial(parser, args)
    terminal.configure_console()
    client = client or terminal.HttpClient(args.url)
    try:
        if args.watch is None:
            return pass_once(client, args, input_fn, out)
        if args.workflow_id:
            return watch_one(client, args, input_fn, out, sleep)
        out(f"Watching for pending workflows every {args.watch:g}s (Ctrl+C to stop)")
        seen: dict[str, str] = {}
        header: list[int] = []
        while True:
            pass_once(client, args, input_fn, out, seen, header)
            sleep(args.watch)
    except terminal.InputClosed as exc:
        out(f"  stopped: {exc}")
        return 0
    except terminal.ServerUnavailable as exc:
        return terminal.fail(str(exc), out)
    except KeyboardInterrupt:
        out("\nstopped")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
