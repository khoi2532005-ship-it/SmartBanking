"""Terminal human review: decide on workflows waiting in awaiting_human_review.

    python -m multi_agent_server.review                      # prompt for each pending workflow
    python -m multi_agent_server.review --watch 5            # keep polling every 5 s (demo mode)
    python -m multi_agent_server.review --id wf_1234abcd --decision accept --note "ok"

Each decision goes to POST /workflow/<id>/decision, the same endpoint the UI
uses, so the audit shows who decided (by: terminal) and the response is only
released after this step.
"""

from __future__ import annotations

import argparse
import time
from typing import Any, Callable

from multi_agent_server import terminal
from multi_agent_server.models import DECISIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m multi_agent_server.review",
                                     description="Human review of pending multi-agent workflows.")
    parser.add_argument("--url", default=None, help="server URL (default: MULTI_AGENT_HOST/PORT from .env)")
    parser.add_argument("--id", dest="workflow_id", default=None, help="review one workflow only")
    parser.add_argument("--decision", choices=list(DECISIONS), default=None,
                        help="decide without prompting (use with --id or for every pending workflow)")
    parser.add_argument("--note", default="", help="correction note to record with --decision")
    parser.add_argument("--by", default="terminal", help="who is deciding, recorded in the audit")
    parser.add_argument("--watch", type=float, default=None, metavar="SECONDS",
                        help="keep polling for new pending workflows every SECONDS")
    return parser


def review_one(client: Any, workflow_id: str, args: argparse.Namespace, input_fn: Callable[[str], str],
               out: Callable[[str], None]) -> bool:
    """Show one workflow and record a decision. Returns True when a decision was sent."""
    status, full = client.get(f"/workflow/{workflow_id}")
    if status != 200:
        out(f"  {workflow_id}: {full.get('error', status)}")
        return False
    out("")
    out(terminal.render_workflow(full))
    if full["state"] != "awaiting_human_review":
        out(f"  {workflow_id} is {full['state']}; nothing to decide.")
        return False
    if args.decision:
        decision, note = args.decision, args.note
    else:
        decision, note = terminal.prompt_decision(input_fn, out)
        if decision is None:
            out("  skipped")
            return False
    status, body = terminal.send_decision(client, workflow_id, decision, note, args.by)
    if status != 200:
        out(f"  decision rejected ({status}): {body.get('error')}")
        return False
    out(f"  -> {body['state']}" + ("; response released" if body["released"] else "; response withheld"))
    out(terminal.render_response(body["final_response"]))
    return True


def pass_once(client: Any, args: argparse.Namespace, input_fn: Callable[[str], str],
              out: Callable[[str], None]) -> int:
    if args.workflow_id:
        return 0 if review_one(client, args.workflow_id, args, input_fn, out) else 1
    status, pending = client.get("/workflows/pending")
    if status != 200:
        return terminal.fail(f"server answered {status}: {pending.get('error')}", out)
    out(f"Multi-Agent Server at {client.base_url} - {pending['count']} workflow(s) awaiting human review")
    for item in pending["workflows"]:
        review_one(client, item["workflow_id"], args, input_fn, out)
    return 0


def main(argv: list[str] | None = None, *, client: Any | None = None,
         input_fn: Callable[[str], str] = input, out: Callable[[str], None] = terminal.stdout) -> int:
    args = build_parser().parse_args(argv)
    client = client or terminal.HttpClient(args.url)
    try:
        if args.watch is None:
            return pass_once(client, args, input_fn, out)
        out(f"Watching for pending workflows every {args.watch:g}s (Ctrl+C to stop)")
        while True:
            code = pass_once(client, args, input_fn, out)
            if code and args.workflow_id:
                return code
            time.sleep(args.watch)
    except terminal.ServerUnavailable as exc:
        return terminal.fail(str(exc), out)
    except KeyboardInterrupt:
        out("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
