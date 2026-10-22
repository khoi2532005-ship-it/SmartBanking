# Local deployment: multi-terminal run, 2026-10-21

One run of the Release 2 system on a MacBook, with each server in its own terminal as the
run sheet in the root README describes, driven from a fifth terminal. Every block below is the
output that terminal printed (colour codes removed, the checkout path shown as `<repo>`, and the
repeated start-up `/health` polls collapsed). The commit under test is `2c7fa3a` (branch
`release2-review-modes`), as the validation record states.

| Terminal | Process | Port |
|---|---|---|
| 1 | `python -m mcp_server.server` (shared MCP server, host process) | 8100 |
| 2 | `python -m rag_server.server` (shared RAG server, host process) | 8200 |
| 3 | `python -m multi_agent_server.server` (shared Multi-Agent server, host process) | 8300 |
| 4 | the budgeting, accounts and transactions database and API services | 5014/5004, 5011/5001, 5015/5005 |
| 5 | the terminal runners and the agentic loop | - |

Docker was not available on the machine that made this run, so terminal 4 started the database and
API services as host processes (`python app.py` in each service folder) instead of
`docker compose up --build -d`. The services, ports and calls are the same; the containerised
version of terminal 4 is in the run sheet. The frontend was not started in this run: the UI side of
the same flow is in `../../multi-agent/budgeting/` (headless Chrome driving the AI Mode tab).

The same run with terminal 4 as `docker compose up --build -d` on a Windows PC with Docker Desktop: [multi-terminal-docker-run-20261022.md](multi-terminal-docker-run-20261022.md).

## Terminal 1 - shared MCP server

```
========================================================================
  SmartBank - shared MCP server (not containerised)
  listening:  http://0.0.0.0:8100/mcp
  local url:  http://localhost:8100/mcp
  containers: http://host.docker.internal:8100/mcp
  tools:      budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending
  feature APIs:
    accounts      http://localhost:5001
    loans         http://localhost:5002
    fraud         http://localhost:5003
    budgeting     http://localhost:5004
    transactions  http://localhost:5005
  validate:   python -m mcp_server.validate
========================================================================
Tool 'no_such_tool' not listed, no validation will be performed
```

## Terminal 2 - shared RAG server

```
  index built: {'chunks': 67, 'sources': 9, 'vector_indexed': 67, 'mode': 'hybrid'}
========================================================================
  SmartBank - shared RAG server (not containerised)
  listening:  http://0.0.0.0:8200
  local url:  http://localhost:8200
  containers: http://host.docker.internal:8200
  corpus:     67 chunks from 9 sources (80-word max, 256-d embeddings, k=5)
  retrieval:  hybrid
  generator:  gemini / gemini-flash-lite-latest
  validate:   python -m rag_server.validate
========================================================================
 * Serving Flask app 'server'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8200
 * Running on http://<lan-ip>:8200
Press CTRL+C to quit
127.0.0.1 - - [21/Oct/2026 11:36:45] "GET /health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:32] "POST /retrieve HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:38] "POST /query HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:38] "POST /query HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:38] "POST /query HTTP/1.1" 200 -
... (2 more GET /health 200 lines from the start-up wait, omitted)
```

## Terminal 3 - shared Multi-Agent server

```
========================================================================
  SmartBank Multi-Agent Server (Release 2) - host process, not a container
  listening:  http://localhost:8300
  pipeline:   planner -> worker -> reviewer -> human (then the human decision)
  workflows:  0 loaded from <repo>/multi_agent_server/data
  audit:      <repo>/multi_agent_server/data/audit/workflow_history.jsonl
              <repo>/multi_agent_server/data/audit/coordination_audit.jsonl
  containers: http://host.docker.internal:8300
  auth:       open - set MULTI_AGENT_API_TOKEN in .env to require a bearer token
========================================================================
 * Serving Flask app 'server'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8300
 * Running on http://<lan-ip>:8300
Press CTRL+C to quit
127.0.0.1 - - [21/Oct/2026 11:35:41] "GET /health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:46] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [21/Oct/2026 11:36:46] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:47] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:48] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:49] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:50] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:51] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:52] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:53] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:54] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:55] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:56] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:57] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:58] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:59] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:00] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:01] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:02] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:03] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:04] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:05] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:06] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:07] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflow/wf_2fc78a04/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflow/wf_2fc78a04 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflow/wf_2fc78a04/response HTTP/1.1" 409 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflows/pending HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "POST /workflow/wf_2fc78a04/decision HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflow/wf_2fc78a04/response HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [21/Oct/2026 11:37:08] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:09] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:10] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:11] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:12] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:13] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:14] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:15] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:16] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:17] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:18] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:19] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:20] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:21] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:22] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:23] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:24] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:25] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:26] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:27] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:28] "GET /workflow/wf_192378fa/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:28] "POST /workflow/wf_192378fa/decision HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:28] "GET /workflow/wf_192378fa/response HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:29] "GET /metrics?workflows=wf_2fc78a04,wf_192378fa HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:16] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [21/Oct/2026 11:38:16] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:17] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:18] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:19] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:20] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:21] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:22] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:23] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:24] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:25] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:26] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:27] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:28] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:29] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:30] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:31] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:32] "GET /workflow/wf_ce57b3dd/status HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:32] "GET /workflow/wf_ce57b3dd HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:33] "POST /workflow/wf_ce57b3dd/decision HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:33] "GET /workflow/wf_ce57b3dd/response HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:33] "GET /workflows/pending HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:33] "GET /metrics HTTP/1.1" 200 -
... (30 more GET /health 200 lines from the start-up wait, omitted)
```

## Terminal 4 - feature services

Requests the budgeting API answered during the run:

```
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5004
 * Running on http://<lan-ip>:5004
Press CTRL+C to quit
127.0.0.1 - - [21/Oct/2026 11:35:41] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:42] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:43] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:44] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:45] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:46] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:47] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:48] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:49] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:50] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:52] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:53] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:54] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:55] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:56] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:57] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:58] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:35:59] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:00] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:01] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:03] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:04] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:05] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:06] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:07] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:08] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:09] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:10] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:11] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:12] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:12] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:37] "GET /api/health HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:41] "GET /api/budgets/summary?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:36:53] "GET /api/budgets/summary?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:15] "GET /api/transactions/spending?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:37:15] "GET /api/budgets/summary?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:38:22] "GET /api/budgets/summary?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
127.0.0.1 - - [21/Oct/2026 11:39:23] "GET /api/budgets/summary?customer_id=1&month=9&year=2026 HTTP/1.1" 200 -
```

## Terminal 5 - health checks

```
=== health
http://localhost:8100/mcp -> 406
http://localhost:8300/health -> 200
http://localhost:5004/api/health -> 200
{"llm":"gemini","mcp":{"enabled":true,"url":"http://localhost:8100/mcp"},"multi_agent":{"enabled":true,"url":"http://localhost:8300"},"rag":{"enabled":true,"url":"http://localhost:8200"},"service":"budgets-service","status":"running"}
```

## Terminal 5 - Multi-Agent validation record

Written to `docs/evidence/multi-agent-validation-20261021T003729Z.json`, with the audit snapshot under
`docs/evidence/multi_agent/validation-20261021T003729Z/`.

```
$ python -m multi_agent_server.validate --evidence
========================================================================
  SmartBank Multi-Agent Server - terminal validation
  server:  http://localhost:8300
  commit:  2c7fa3a
========================================================================
  PASS  1. server reachable
        call:      GET /health  
        expected:  service multi-agent-server with a four-stage pipeline
        observed:  HTTP 200; pipeline planner -> worker -> reviewer -> human; roles ['planner', 'worker', 'reviewer']; models {'planner': 'shared AI-Mode model', 'reviewer': 'shared AI-Mode model', 'worker': 'shared AI-Mode model'}; max_revisions 1
  PASS  2. full workflow reaches the human gate
        call:      POST /workflow + poll /status  {"feature": "budgeting", "request": "Which budget categories went over the limit in September 2026 and by how much?", "context": {"customer_id": 1, "month": 9, 
        expected:  planner, worker and reviewer complete; state awaiting_human_review with plan, evidence and review
        observed:  wf_2fc78a04 -> awaiting_human_review; stages ['planner#1 completed 7.402s', 'worker#1 completed 6.952s', 'reviewer#1 completed 7.669s', 'human#1 running']; plan 2 tasks (model); evidence 1/1 ok; review accept (model)
  PASS  3. response withheld until a person decides
        call:      GET /workflow/<id>/response  {"workflow_id": "wf_2fc78a04"}
        expected:  HTTP 409 with awaiting_decision true; the workflow is listed under /workflows/pending
        observed:  HTTP 409: no response yet: the workflow has not been decided by a human; pending 1 incl. this one: True
  PASS  4. accept releases the final response
        call:      POST /workflow/<id>/decision  {"decision": "accept", "note": "", "by": "validate"}
        expected:  state accepted; GET /response is 200 with released true and the Worker's answer
        observed:  decision HTTP 200 -> accepted; response HTTP 200, released True, answer 126 chars, decided_by validate
  PASS  5. rejected workflow recorded, nothing released
        call:      POST /workflow, then decision reject  {"feature": "budgeting", "request": "What did I spend most on in September 2026, and is my overall budget on track?", "context": {"customer_id": 1, "month": 9, 
        expected:  state rejected; GET /response is 200 with released false and the note kept
        observed:  wf_192378fa -> rejected; response HTTP 200, released False, answer None, note kept True
  PASS  6. audit files written
        call:      read workflow_history.jsonl and coordination_audit.jsonl  {"coordination_audit": "multi_agent_server/data/audit/coordination_audit.jsonl", "workflow_history": "multi_agent_server/data/audit/workflow_history.jsonl"}
        expected:  for each workflow above: created, every stage started and finished, the gate state, the exact decision this run posted, and workflow_completed
        observed:  36 history records, 22 coordination records for 2 workflows; per workflow: created, every stage started and finished, the gate state, the decision posted and workflow_completed - all present
  PASS  7. handoff contracts reject off-contract outputs
        call:      contracts.validate_plan / validate_result / validate_review  {"plan": "unknown endpoint + another customer", "result": "invented figure", "review": "accept with an unmet criterion"}
        expected:  each is rejected with the reasons listed; nothing off-contract reaches the next role
        observed:  plan: task t1: endpoint '/api/customers' is not in the budgeting catalogue ['/api/budgets/summary', '/api/transactions/spending', '/api/budgets', '/api/budgets/insights', '/api/categories']; result: finding 1: the number 9999.00 is not in the evidence; copy figures exactly from it or leave them out; review: verdict accept is not allowed while criteria [1] are unmet; return revise with revision_notes
  PASS  8. feature API down -> structured error, no invented result
        call:      in-process server, budgeting -> http://127.0.0.1:9  {"feature": "budgeting", "request": "Which budget categories went over the limit in September 2026 and by how much?", "context": {"customer_id": 1, "month": 9, 
        expected:  state failed; error names the unreachable URL; evidence records carry the errors; worker_blocked audited
        observed:  wf_e910cdf8 -> failed; error: worker: no feature API answered: budgeting service unavailable: connection refused at http://127.0.0.1:9/api/budgets/summary - is the service running?
  PASS  9. coordination metrics computed from the audit files
        call:      GET /metrics  {"workflows": "wf_2fc78a04,wf_192378fa"}
        expected:  rates and stage times derived from the two JSONL files, covering the workflows above
        observed:  HTTP 200; workflows 2 (2 decided); plan acceptance 1.0, worker completion 1.0, handoff success 1.0, defect yield 0.0, rework 0.0, fallback 0.0, human acceptance 0.5; stage s {'human': 0.0, 'planner': 7.17, 'reviewer': 7.046, 'worker': 6.458}; end-to-end s {'to_decision': 21.0, 'to_human_gate': 21.0}
========================================================================
  9/9 checks passed, 0 skipped  (all three models took part)
========================================================================
  evidence: docs/evidence/multi-agent-validation-20261021T003729Z.json
  evidence: docs/evidence/multi_agent/validation-20261021T003729Z/workflow_history.jsonl
  evidence: docs/evidence/multi_agent/validation-20261021T003729Z/coordination_audit.jsonl
```

## Terminal 5 - one workflow from the terminal, decided by a person

```
$ python -m multi_agent_server.run --feature budgeting --customer 1 --month 9 --year 2026 --request "Which budget categories went over the limit in September 2026, and by how much?" --decision partially_accept --note "Name the month as September 2026 in the answer" --by terminal:Bao
Started wf_ce57b3dd (budgeting) at http://localhost:8300; following the stages:
  planner  attempt 1  completed  5.345s  gemini / gemini-flash-lite-latest
  worker   attempt 1  completed  5.526s  gemini / gemini-flash-lite-latest
  reviewer attempt 1  completed  4.374s  gemini / gemini-flash-lite-latest

wf_ce57b3dd  budgeting  state awaiting_human_review  created 2026-10-21T00:38:16+00:00
  Request:  Which budget categories went over the limit in September 2026, and by how much?
  Context:  {"customer_id": 1, "month": 9, "year": 2026}
  Plan:     Retrieve the budget summary for customer 1 for September 2026 and identify
            categories that went over their limit along with the exact over-budget amounts. (2
            tasks, source model, gemini / gemini-flash-lite-latest)
            t1 GET /api/budgets/summary {"customer_id": 1, "month": 9, "year": 2026}
            t2 analysis (after t1): Review the budget summary from t1 to identify any categories where status indicates over the limit or spend exceeds the limit, and calculate or record the exact amount by which they went over.
  Evidence: t1 http://localhost:5004/api/budgets/summary -> ok HTTP 200 0.024s
  Finding:  t2 <- t1: In September 2026, Dining Out went over its limit by 25.2 and Shopping
            went over its limit by 74.9.
  Answer:   In September 2026, two budget categories went over their limits. Dining Out exceeded
            its monthly limit by 25.2, and Shopping exceeded its monthly limit by 74.9. [source
            model, attempt 1]
  Review:   accept [source model, attempt 1, criteria met 2/2]
            The Worker successfully retrieved the budget summary for customer 1 for September
            2026 using the budget summary endpoint, correctly identifying Dining Out and
            Shopping as the over-budget categories with their respective over-budget amounts
            from the evidence.

  Awaiting your decision. The response is not released until you decide.

  Decision partially_accept: response released at 2026-10-21T00:38:33+00:00 by terminal:Bao
  Answer:   In September 2026, two budget categories went over their limits. Dining Out exceeded
            its monthly limit by 25.2, and Shopping exceeded its monthly limit by 74.9.
  Correction: Name the month as September 2026 in the answer
```

```
$ python -m multi_agent_server.review
Multi-Agent Server at http://localhost:8300 - 0 workflow(s) awaiting human review
```

## Terminal 5 - coordination metrics from the audit files

```
$ curl -s "http://localhost:8300/metrics"
{
    "counts": {
        "contract_rejections": 0,
        "coordination_records": 33,
        "escalations": 0,
        "fallbacks": 0,
        "handoff_anomalies": 0,
        "handoffs": 9,
        "history_records": 54,
        "revisions_requested": 0,
        "rolled_back_decisions": 0,
        "stages_finished": {
            "human": 3,
            "planner": 3,
            "reviewer": 3,
            "worker": 3
        },
        "stages_started": {
            "human": 3,
            "planner": 3,
            "reviewer": 3,
            "worker": 3
        },
        "timeouts": 0
    },
    "end_to_end_seconds": {
        "to_decision": 19.667,
        "to_human_gate": 19.333
    },
    "escalation_rate": 0.0,
    "fallback_rate": 0.0,
    "handoff_success_rate": 1.0,
    "human_acceptance_rate": 0.667,
    "human_decisions": {
        "accept": 1,
        "partially_accept": 1,
        "reject": 1
    },
    "plan_acceptance_rate": 1.0,
    "reviewer_defect_yield": 0.0,
    "rework_ratio": 0.0,
    "scope": "all",
    "stage_seconds": {
        "human": 0.333,
        "planner": 6.562,
        "reviewer": 6.156,
        "worker": 6.148
    },
    "worker_completion_rate": 1.0,
    "workflows": {
        "by_final_state": {
            "accepted": 1,
            "partially_accepted": 1,
            "rejected": 1
        },
        "decided": 3,
        "failed": 0,
        "total": 3
    }
}
```

## Terminal 5 - agentic loop: the three Release 2 review modes and the two Release 1 validation modes

Each run also wrote `docs/evidence/<mode>-<timestamp>.json` and a row in `docs/evidence/evidence-log.md`.

### multi_agent_review

```
$ python agentic_loop.py --mode multi_agent_review

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [Multi-Agent Workflow Review] PLAN     Review the Multi-Agent workflow evidence (workflow_history.jsonl and coordination_audit.jsonl) and produce review recommendations grounded in those records
  [Multi-Agent Workflow Review]            - both audit files exist and hold records (the running server, a validation snapshot or committed evidence)
  [Multi-Agent Workflow Review]            - every reviewed workflow is rebuilt from its records: stages, reviewer verdict, revisions, the human decision, the release
  [Multi-Agent Workflow Review]            - the coordination metrics (plan acceptance, worker completion, handoff success, human acceptance) come from the same records
  [Multi-Agent Workflow Review]            - the entry names only workflow ids in the records, every one of the four stages, and quotes each decision and metric exactly
  [Multi-Agent Workflow Review]            - a workflow that failed, a fallback stage or a handoff anomaly makes the verdict ATTENTION, never PASS
  [Multi-Agent Workflow Review] ACT      collecting evidence
  [Multi-Agent Workflow Review] OBSERVE  3 workflow(s) from the running server's audit folder (multi_agent_server/data/audit): wf_2fc78a04 accepted (accept by validate), wf_192378fa rejected (reject by validate), wf_ce57b3dd partially_accepted (partially_accept by terminal:Bao). Stages planner 3/3, worker 3/3, reviewer 3/3, human 3/3; fallbacks 0; revisions 0. Decisions accept 1, partially_accept 1, reject 1, pending 0, failed 0. plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.67
  [Multi-Agent Workflow Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Multi-Agent Workflow Review] OBSERVE  answer accepted
  [Multi-Agent Workflow Review] REVIEW   second opinion from the review model

  --- multi_agent_review result ----------------------------------
  Evidence: 3 workflow(s) from the running server's audit folder (multi_agent_server/data/audit): wf_2fc78a04 accepted (accept by validate), wf_192378fa rejected (reject by validate), wf_ce57b3dd partially_accepted (partially_accept by terminal:Bao). Stages planner 3/3, worker 3/3, reviewer 3/3, human 3/3; fallbacks 0; revisions 0. Decisions accept 1, partially_accept 1, reject 1, pending 0, failed 0. plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.67

  Attempt 1 output:
    Workflows: 3 reviewed - wf_2fc78a04, wf_192378fa, wf_ce57b3dd
    Stages: planner 3/3, worker 3/3, reviewer 3/3, human 3/3; fallbacks 0; revisions 0
    Decisions: accept 1, partially_accept 1, reject 1; wf_2fc78a04 accept, wf_192378fa reject, wf_ce57b3dd partially_accept
    Metrics: plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.67
    Recommendation: Keep the current workflow configuration since all stages completed successfully and handoffs succeeded without anomalies or revisions.
    Verdict: PASS - All stages completed successfully with zero fallbacks, revisions, or handoff anomalies.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: The recommendation and verdict claim that all stages completed successfully and without anomalies, but the evidence shows that workflow wf_192378fa was rejected and human acceptance is 0.67.
    Correction: Revise the recommendation and verdict to acknowledge that one workflow was rejected and human acceptance is partial, rather than generalizing that everything succeeded without issue.
    Retest: Re-verify that the recommendation and verdict accurately reflect the mixed outcomes (accept, reject, partially_accept) present in the workflow audit data.

  RESULT: PASS
  evidence: docs/evidence/multi_agent_review-20261021T003854Z.json
```

### testing_review

```
$ python agentic_loop.py --mode testing_review

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [Testing Report Review] PLAN     Review every student's pre-commit security report and post-commit endpoint test report and write the Testing Review entry from their figures
  [Testing Report Review]            - the reports under docs/testing follow the team naming convention (student-1 to student-5)
  [Testing Report Review]            - each pre-commit report names its scans with findings, fixed and accepted counts and a result
  [Testing Report Review]            - each post-commit report names the endpoints tested, their outcomes and the check count (or JUnit totals)
  [Testing Report Review]            - the entry quotes every scan name, count, outcome and the coverage exactly as the reports say
  [Testing Report Review]            - a failed report or a student without a report makes the verdict ATTENTION, never PASS
  [Testing Report Review] ACT      collecting evidence
  [Testing Report Review] OBSERVE  Pre-commit reports: student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; no pre-commit report: student-1, student-2, student-3, student-5. Post-commit reports: student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 27 checks); no post-commit report: student-1, student-2, student-5. Coverage 1 of 5 pre-commit, 2 of 5 post-commit; missing one or both: student-1, student-2, student-3, student-5; failed: none
  [Testing Report Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Testing Report Review] OBSERVE  answer accepted
  [Testing Report Review] REVIEW   second opinion from the review model

  --- testing_review result --------------------------------------
  Evidence: Pre-commit reports: student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; no pre-commit report: student-1, student-2, student-3, student-5. Post-commit reports: student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 27 checks); no post-commit report: student-1, student-2, student-5. Coverage 1 of 5 pre-commit, 2 of 5 post-commit; missing one or both: student-1, student-2, student-3, student-5; failed: none

  Attempt 1 output:
    Pre-commit: student-1 none; student-2 none; student-3 none; student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; student-5 none
    Post-commit: student-1 none; student-2 none; student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 27 checks); student-5 none
    Coverage: 1 of 5 students have a pre-commit report, 2 of 5 have a post-commit report; missing: student-1, student-2, student-3, student-5
    Recommendation: The team must provide missing pre-commit and post-commit testing reports for student-1, student-2, and student-5, and pre-commit reports for student-3.
    Verdict: ATTENTION - Pre-commit and post-commit testing evidence is missing for multiple students.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: The recommendation states that student-3 is missing pre-commit reports, but the evidence states that student-3 is missing one or both reports and has no pre-commit report listed while having a post-commit report, which makes the specific callout of student-3 for pre-commit unsupported or partially contradictory to the aggregate missing list.
    Correction: Revise the recommendation to align strictly with the students listed as missing one or both reports in the evidence without misattributing specific pre-commit status to student-3 beyond the aggregate.
    Retest: Verify that the recommendation only lists students supported by the missing reports data in the evidence.

  RESULT: PASS
  evidence: docs/evidence/testing_review-20261021T003909Z.json
```

### cloud_deployment_review

> Superseded. On `2c7fa3a` the mode approved the sample report below, which it must never do; the PR #65 review
> caught it. Since `12d47a9` the sample is held with verdict ATTENTION, and the rerun is
> `docs/evidence/cloud_deployment_review-20261021T203142Z.json`. The evidence file this block names was removed
> for that reason.

```
$ python agentic_loop.py --mode cloud_deployment_review

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [Cloud Deployment Report Review] PLAN     Review the cloud deployment report and write the entry that supports the final human release decision
  [Cloud Deployment Report Review]            - the report names the provider, region, commit and the cloud-deployment.yml run
  [Cloud Deployment Report Review]            - every endpoint and CRUD check in the report returned its expected status
  [Cloud Deployment Report Review]            - AI-Mode, MCP, RAG and the Multi-Agent Server states are reported as the baseline requires (disabled by default)
  [Cloud Deployment Report Review]            - the entry quotes the provider, commit, counts, statuses and AI states exactly and records the human decision
  [Cloud Deployment Report Review]            - the release recommendation is approve only when every check passed and no issue is open
  [Cloud Deployment Report Review] ACT      collecting evidence
  [Cloud Deployment Report Review] OBSERVE  azure australiaeast, commit 0000000, run 0 success: 3 resources; endpoints 3/3 passed (home page 200, budgeting api health 200, budgets list 200); CRUD 3/3 passed (budget create 201, budget read 200, budget delete 200); AI services ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled; issues 0; recommendation approve; human decision pending
  [Cloud Deployment Report Review] ADAPT    degraded source - this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's real report is not in the repo yet, so nothing here describes a real deployment
  [Cloud Deployment Report Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Cloud Deployment Report Review] OBSERVE  answer accepted
  [Cloud Deployment Report Review] REVIEW   second opinion from the review model

  --- cloud_deployment_review result -----------------------------
  Evidence: azure australiaeast, commit 0000000, run 0 success: 3 resources; endpoints 3/3 passed (home page 200, budgeting api health 200, budgets list 200); CRUD 3/3 passed (budget create 201, budget read 200, budget delete 200); AI services ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled; issues 0; recommendation approve; human decision pending
  DEGRADED: this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's real report is not in the repo yet, so nothing here describes a real deployment

  Attempt 1 output:
    Deployment: azure australiaeast, commit 0000000, workflow run 0 success, 3 resources
    Endpoints: 3/3 passed - home page 200, budgeting api health 200, budgets list 200
    AI services: ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled
    CRUD: 3/3 passed - budget create 201, budget read 200, budget delete 200
    Release recommendation: approve - All deployment checks passed successfully with no open issues.
    Human decision: pending
    Verdict: PASS - All endpoint and CRUD checks passed with expected status codes; this is the sample report.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: No evidence-backed risk identified.
    Correction: No correction required.
    Retest: Repeat validation after future changes.

  RESULT: PASS
  evidence: docs/evidence/cloud_deployment_review-20261021T003922Z.json
```

### mcp_validation

```
$ python agentic_loop.py --mode mcp_validation

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [MCP Server Validation] PLAN     Verify the shared MCP server honours its tool contracts, and that the model's test-record entry reports exactly what was observed
  [MCP Server Validation]            - the MCP server answers initialize at http://localhost:8100/mcp
  [MCP Server Validation]            - tools/list publishes every registered tool with an input schema
  [MCP Server Validation]            - a valid budgeting_summary call returns the declared structured result
  [MCP Server Validation]            - an out-of-range month, a non-integer customer_id and an undeclared argument are rejected before any backend call
  [MCP Server Validation]            - an unknown tool is rejected, never served; a tool whose service is down returns an explicit error, never invented data
  [MCP Server Validation]            - the entry names every tool, quotes the demo call and its totals, accounts for every rejection and matches the pass count
  [MCP Server Validation] ACT      collecting evidence
  [MCP Server Validation] OBSERVE  5 tools on http://localhost:8100/mcp: budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending. Valid call budgeting_summary {"customer_id": 1, "month": 9, "year": 2026} -> 7 budgets, total spent $1,486.78 of $2,160.00, spending source transactions-api. Rejected: {"customer_id": 1, "month": 13, "year": 2026} -> month must be between 1 and 12, got 13; {"customer_id": "abc", "month": 9, "year": 2026} -> 1 validation error for budgeting_summaryArguments customer_id Input should be; {"customer_id": 1, "month": 9, "year": 2026, "sql": "SELECT * FROM budgets"} -> 1 validation error for budgeting_summaryArguments sql Extra inputs are not per; no_such_tool -> Unknown tool: no_such_tool. 8/8 checks passed, 0 skipped
  [MCP Server Validation] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [MCP Server Validation] OBSERVE  answer accepted
  [MCP Server Validation] REVIEW   second opinion from the review model

  --- mcp_validation result --------------------------------------
  Evidence: 5 tools on http://localhost:8100/mcp: budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending. Valid call budgeting_summary {"customer_id": 1, "month": 9, "year": 2026} -> 7 budgets, total spent $1,486.78 of $2,160.00, spending source transactions-api. Rejected: {"customer_id": 1, "month": 13, "year": 2026} -> month must be between 1 and 12, got 13; {"customer_id": "abc", "month": 9, "year": 2026} -> 1 validation error for budgeting_summaryArguments customer_id Input should be; {"customer_id": 1, "month": 9, "year": 2026, "sql": "SELECT * FROM budgets"} -> 1 validation error for budgeting_summaryArguments sql Extra inputs are not per; no_such_tool -> Unknown tool: no_such_tool. 8/8 checks passed, 0 skipped

  Attempt 1 output:
    Tools: 5 registered - budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending
    Demo call: budgeting_summary with {"customer_id": 1, "month": 9, "year": 2026}
    Result: total spent $1,486.78 across 7 budgets; spending source transactions-api
    Rejected: The out-of-range month, non-integer customer_id, undeclared argument, and unknown tool were all rejected with isError True and corresponding error messages from the server.
    Verdict: 8/8 checks passed, 0 skipped - PASS
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: The answer claims the rejections returned `isError True`, which is not stated in the evidence.
    Correction: Remove the reference to `isError True` since the evidence only mentions the specific error messages and rejection details without mentioning `isError`.
    Retest: Re-verify that the rejected error messages match the evidence without claiming specific protocol flags that were not provided.

  RESULT: PASS
  evidence: docs/evidence/mcp_validation-20261021T003931Z.json
```

### rag_validation

```
$ python agentic_loop.py --mode rag_validation

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [RAG Server Validation] PLAN     Verify the shared RAG server retrieves the right evidence, answers only from it with citations and a confidence, refuses off-topic questions, and that the model's evaluation entry reports exactly what was observed
  [RAG Server Validation]            - the RAG server answers /health at http://localhost:8200 with a populated index
  [RAG Server Validation]            - every benchmark question finds a relevant chunk in its top 5 (Precision@5 and Recall@5 recorded)
  [RAG Server Validation]            - a benchmark question returns a grounded answer with at least one citation and a confidence category
  [RAG Server Validation]            - every citation is a retrieved chunk and the expected fact appears in a cited chunk
  [RAG Server Validation]            - off-topic questions return insufficient context with no citations and no model call
  [RAG Server Validation]            - the shared index is left untouched: the refresh check is skipped unless an operator runs it on purpose
  [RAG Server Validation]            - the entry quotes the index size, metrics, confidence and chunk ids exactly and matches the pass count
  [RAG Server Validation] ACT      collecting evidence
  [RAG Server Validation] OBSERVE  67 chunks from 9 documents, retrieval mode hybrid. Mean P@5 0.27, mean R@5 0.94, 6 of 6 benchmark questions found a relevant chunk in the top 5. Grounded answer to "What does the NEAR_LIMIT budget status mean?": confidence Medium, citations budgeting-feature#003. 2 off-topic questions returned insufficient context with no citations and no model call. Refresh skipped: the shared index was not rebuilt by this run. 5/5 checks passed, 1 skipped
  [RAG Server Validation] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [RAG Server Validation] OBSERVE  answer accepted
  [RAG Server Validation] REVIEW   second opinion from the review model

  --- rag_validation result --------------------------------------
  Evidence: 67 chunks from 9 documents, retrieval mode hybrid. Mean P@5 0.27, mean R@5 0.94, 6 of 6 benchmark questions found a relevant chunk in the top 5. Grounded answer to "What does the NEAR_LIMIT budget status mean?": confidence Medium, citations budgeting-feature#003. 2 off-topic questions returned insufficient context with no citations and no model call. Refresh skipped: the shared index was not rebuilt by this run. 5/5 checks passed, 1 skipped

  Attempt 1 output:
    Index: 67 chunks from 9 documents, retrieval mode hybrid
    Retrieval: mean P@5 0.27, mean R@5 0.94, 6 of 6 benchmark questions found a relevant chunk in the top 5
    Grounded answer: confidence Medium, citations budgeting-feature#003
    Off-topic: 2 questions returned insufficient context with no citations and no model call
    Verdict: 5/5 checks passed, 1 skipped - PASS
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: No evidence-backed risk identified.
    Correction: No correction required.
    Retest: Repeat validation after future changes.

  RESULT: PASS
  evidence: docs/evidence/rag_validation-20261021T003944Z.json
```
