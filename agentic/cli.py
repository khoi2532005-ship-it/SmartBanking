"""Menu and argument handling for `python agentic_loop.py`.

Interactive by default (what you want in front of a marker), with flags for
CI and for demoing one feature quickly:

    python agentic_loop.py                 # menu
    python agentic_loop.py --mode fraud    # one feature, no menu
    python agentic_loop.py --all           # every implemented feature + summary
    python agentic_loop.py --all --quiet   # same, exit code only (CI)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agentic_loop.py",
        description="SmartBank shared agentic loop: Plan -> Act -> Observe -> Adapt.",
    )
    parser.add_argument("--mode", help="run one feature and exit (e.g. fraud)")
    parser.add_argument("--all", action="store_true", help="run every implemented feature")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress the menu; exit non-zero if any run fails")
    parser.add_argument("--attempts", type=int, default=None,
                        help="retry budget per feature (default 2)")
    return parser.parse_args(argv)


def _run_one(key, loop, modes, reporter, attempts):
    mode = modes.MODES[key]
    kwargs = {"max_attempts": attempts} if attempts else {}
    result = loop.run(mode, **kwargs)
    reporter.result(result)
    path = reporter.write_evidence(result)
    print(f"  evidence: {path.relative_to(REPO_ROOT)}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    # Load .env before importing anything that reads os.getenv at import time.
    load_dotenv(dotenv_path=REPO_ROOT / ".env")

    from agentic import llm, loop, reporter
    from agentic import modes

    reporter.header("SmartBank - Shared Agentic Loop", llm.describe())

    if not modes.MODES:
        print("  No modes implemented yet. Start from agentic/modes/_template.py.")
        return 1

    # ---- non-interactive paths -----------------------------------------
    if args.mode:
        if args.mode not in modes.MODES:
            known = ", ".join(modes.MODES) or "none"
            pending = ", ".join(modes.PENDING)
            print(f"  Unknown mode '{args.mode}'. Implemented: {known}. Pending: {pending}.")
            return 2
        result = _run_one(args.mode, loop, modes, reporter, args.attempts)
        return 0 if result.ok else 1

    if args.all or args.quiet:
        results = [_run_one(key, loop, modes, reporter, args.attempts) for key in modes.MODES]
        reporter.summary(results)
        return 0 if all(r.ok for r in results) else 1

    # ---- interactive menu ------------------------------------------------
    order = list(modes.MODES)
    while True:
        print()
        print("  Options:")
        for i, key in enumerate(order, 1):
            mode = modes.MODES[key]
            print(f"    {i} - {mode.label} ({mode.owner})")
        for label, owner in modes.PENDING.values():
            print(f"    - - {label} ({owner}) - not implemented yet")
        print(f"    {len(order) + 1} - Run all")
        print("    0 - Exit")

        try:
            choice = input("  Choose a feature: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice == "0":
            print("  Loop closed.")
            return 0

        if choice == str(len(order) + 1):
            results = [_run_one(key, loop, modes, reporter, args.attempts) for key in order]
            reporter.summary(results)
            continue

        if choice.isdigit() and 1 <= int(choice) <= len(order):
            _run_one(order[int(choice) - 1], loop, modes, reporter, args.attempts)
            continue

        print(f"  Invalid choice. Pick 0-{len(order) + 1}.")
