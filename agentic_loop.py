#!/usr/bin/env python3
"""SmartBank - shared agentic loop.  Plan -> Act -> Observe -> Adapt.

The single loop for the whole integrated application, as required by the
project specification (4.3 Shared Team Agentic Loop: "the workflow shall be
implemented by the integrated team application"). Each student's feature plugs
in as a mode and is demonstrated from the same menu, which also satisfies the
individual requirement to demonstrate the workflow (2.2).

Usage
-----
    python agentic_loop.py                  interactive menu (use this to demo)
    python agentic_loop.py --mode fraud     run one feature
    python agentic_loop.py --all            run every implemented feature
    python agentic_loop.py --all --quiet    CI mode; exit code only

Setup
-----
    cp .env.example .env        # then set GEMINI_API_KEY
    pip install -r requirements-agentic.txt
    docker compose up -d        # the loop talks to the running services

Adding your feature
-------------------
Copy agentic/modes/_template.py, implement four methods, register it in
agentic/modes/__init__.py. See docs/agentic-loop.md.
"""

import sys

from agentic.cli import main

if __name__ == "__main__":
    sys.exit(main())
