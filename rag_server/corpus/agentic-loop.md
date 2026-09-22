---
source_id: agentic-loop
title: Shared agentic loop
authority_tier: 2
origin: docs/agentic-loop.md (extract, 2026-09-22)
---

# One loop for the whole application

The shared agentic loop implements Plan, Act, Observe, Adapt once for the integrated team application, as required by project specification section 4.3. Each feature is a mode on one menu, so every student demonstrates their own slice of the same loop. It runs on the host from the repo root with python agentic_loop.py and talks to the running services over HTTP. It is not a container.

# What the engine does

PLAN calls mode.plan() to state the goal and checks up front. ACT calls mode.collect() to gather deterministic facts with no LLM call; if the evidence is unusable the run stops and spends no tokens. ACT then calls mode.build_prompt() and llm.ask() with the implementation model. OBSERVE calls mode.validate() to check the answer against the facts. ADAPT feeds the rejection reasons back into the prompt and runs ACT again, bounded to two attempts by default. REVIEW asks the review model for a second opinion on an accepted answer; it is advisory and never overturns the verdict.

# Rules the engine enforces

No LLM call on bad evidence: if collect() returns ok=False nothing is sent to the model. Degraded is not the same as passing: if collect() returns degraded=True the run continues but says so in the console and the evidence log.

# Commands

python agentic_loop.py opens the interactive menu. python agentic_loop.py --mode fraud runs one feature. python agentic_loop.py --all runs every implemented feature with a summary. python agentic_loop.py --all --quiet is the CI form and returns only an exit code. Install dependencies with pip install -r requirements-agentic.txt.

# Adding a feature mode

Copy agentic/modes/_template.py, implement plan, collect, build_prompt and validate, register the class in agentic/modes/__init__.py, and put prompts in prompts/<feature>/ as text files, never inline in Python. A good validate() could reject a fluent answer that is wrong; reasons are phrased as instructions to the model because they go straight into the retry prompt.

# Evidence

Every run writes docs/evidence/<mode>-<timestamp>.json with the plan, evidence, every attempt and every verdict, and appends one row to docs/evidence/evidence-log.md. Ten engine tests in tests/test_agentic_loop.py stub the LLM and need no services; test_adapt_retries_and_recovers proves the loop loops.

# Release 1 modes

Release 1 adds an MCP validation mode and a RAG validation mode to the same engine. The MCP mode checks the shared MCP server is reachable, lists its tools, returns a structured result for a valid call and rejects an invalid call. The RAG mode checks that an answerable query returns citations and a confidence category and that an off-topic query returns the insufficient-context response.
