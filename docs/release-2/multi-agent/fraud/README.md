# Fraud Alerts - Release 2 Multi-Agent evidence

Captured on 2026-10-19 against the full local deployment: `docker compose up --build -d`, plus the
MCP (8100), RAG (8200) and Multi-Agent (8300) servers as host processes, with Gemini as the model.

| File | What it shows |
|---|---|
| `terminal-run.txt` | `python -m multi_agent_server.run --feature fraud`: Planner → Worker → Reviewer, the human decision prompt, then accept |
| `ui-1-awaiting-human-review.png`, `ui-2-partially-accepted.png` | the AI Mode panel: a workflow waiting for the decision, then partially accepted with a correction note (released) |
| `ui-3-awaiting-human-review.png`, `ui-4-rejected.png` | a second workflow, then rejected (response withheld) |
| `ui-5-history.png` | the panel's History list |
| `workflow_history.jsonl`, `coordination_audit.jsonl` | every audit record of the six fraud workflows on this machine. Three of them are verification runs from development, and `wf_5eb396ab` was left waiting for a decision |
| `../../deployment/local/fraud-ai-mode.png` | the whole AI Mode tab, with Explain, MCP, RAG and Multi-Agent all answering |

The screenshots were taken with headless Chromium (Playwright) driving the real pages.

The CI run link and endpoint-test results are in `docs/release-2/ci/student-3/`.

Still to add: `docs/release-2/security/student-3-precommit.txt`, once the group's `.pre-commit-config.yaml` is on main.
