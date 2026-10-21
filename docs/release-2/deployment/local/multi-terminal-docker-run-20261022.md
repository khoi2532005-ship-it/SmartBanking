# Local deployment: multi-terminal run with Docker Compose, 2026-10-22

One run of the Release 2 system on a **Windows PC with Docker Desktop**, with each server in its own
PowerShell window as the run sheet in the root README describes, driven from a fifth window. The
frontend, backend/API and database microservices run in Docker Compose; the MCP, RAG and
Multi-Agent servers and the agentic loop run on the host. Every block below is the output that
window printed (colour codes removed, the checkout path shown as `<repo>`, repeated `/health` polls
collapsed, and PowerShell's `NativeCommandError` wrapper around the first stderr line of a native
command reduced to that line). The commit under test is `78df53c` (branch `release2-local-docker-run`,
based on `release2-review-modes`), as the validation record states.

Before this run the Compose volumes were reset with `docker compose down -v`, so every database started from its image's seed; terminal 4 shows it.

| Terminal | Process | Port |
|---|---|---|
| 1 | `python -m mcp_server.server` (shared MCP server, host process) | 8100 |
| 2 | `python -m rag_server.server` (shared RAG server, host process) | 8200 |
| 3 | `python -m multi_agent_server.server` (shared Multi-Agent server, host process) | 8300 |
| 4 | `docker compose up --build -d`: the five features' frontend, backend/API and database containers, and the home page | 3000-3005, 5001-5005, 5011-5015 |
| 5 | the health checks, the terminal runners, the agentic loop and the endpoint tests | - |

This is the Docker counterpart of [multi-terminal-run-20261021.md](multi-terminal-run-20261021.md), which ran terminal 4 as host processes on a Mac without Docker.

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
```

## Terminal 2 - shared RAG server

```
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
 * Running on http://192.168.50.121:8200
Press CTRL+C to quit
127.0.0.1 - - [22/Oct/2026 08:13:09] "GET /health HTTP/1.1" 200 -
... (3 more GET /health 200 lines, omitted)
127.0.0.1 - - [22/Oct/2026 08:26:51] "POST /query HTTP/1.1" 200 -
```

## Terminal 3 - shared Multi-Agent server

```
========================================================================
  SmartBank Multi-Agent Server (Release 2) - host process, not a container
  listening:  http://localhost:8300
  pipeline:   planner -> worker -> reviewer -> human (then the human decision)
  workflows:  24 loaded from <repo>\multi_agent_server\data
  audit:      <repo>\multi_agent_server\data\audit\workflow_history.jsonl
              <repo>\multi_agent_server\data\audit\coordination_audit.jsonl
  containers: http://host.docker.internal:8300
  auth:       open - set MULTI_AGENT_API_TOKEN in .env to require a bearer token
========================================================================
 * Serving Flask app 'server'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:8300
 * Running on http://192.168.50.121:8300
Press CTRL+C to quit
127.0.0.1 - - [22/Oct/2026 08:13:11] "GET /health HTTP/1.1" 200 -
... (3 more GET /health 200 lines, omitted)
127.0.0.1 - - [22/Oct/2026 08:14:07] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [22/Oct/2026 08:14:09] "GET /workflow/wf_5c90e33e/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:12] "GET /workflow/wf_5c90e33e/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:14] "GET /workflow/wf_5c90e33e HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:16] "GET /workflow/wf_5c90e33e/response HTTP/1.1" 409 -
127.0.0.1 - - [22/Oct/2026 08:14:18] "GET /workflows/pending HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:20] "POST /workflow/wf_5c90e33e/decision HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:22] "GET /workflow/wf_5c90e33e/response HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:24] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [22/Oct/2026 08:14:26] "GET /workflow/wf_06af6121/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:29] "GET /workflow/wf_06af6121/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:31] "POST /workflow/wf_06af6121/decision HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:33] "GET /workflow/wf_06af6121/response HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:39] "GET /metrics?workflows=wf_5c90e33e,wf_06af6121 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:44] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [22/Oct/2026 08:14:46] "GET /workflow/wf_2df0254b/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:49] "GET /workflow/wf_2df0254b/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:14:51] "GET /workflow/wf_2df0254b HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:18:20] "GET /workflow/wf_2df0254b HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:18:22] "POST /workflow/wf_2df0254b/decision HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:18:29] "GET /workflows/pending HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:26:19] "GET /workflows?feature=budgeting&limit=10&customer_id=1 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:26:19] "GET /health HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:42] "POST /workflow HTTP/1.1" 202 -
127.0.0.1 - - [22/Oct/2026 08:27:42] "GET /workflow/wf_6956623d HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:42] "GET /workflows?feature=budgeting&limit=10&customer_id=1 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:44] "GET /workflow/wf_6956623d HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:46] "GET /workflow/wf_6956623d HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:48] "GET /workflow/wf_6956623d HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:48] "GET /workflows?feature=budgeting&limit=10&customer_id=1 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:56] "GET /workflow/wf_6956623d/status HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:56] "POST /workflow/wf_6956623d/decision HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:56] "GET /workflow/wf_6956623d HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:27:56] "GET /workflows?feature=budgeting&limit=10&customer_id=1 HTTP/1.1" 200 -
127.0.0.1 - - [22/Oct/2026 08:42:28] "GET / HTTP/1.1" 404 -
127.0.0.1 - - [22/Oct/2026 08:42:28] "GET /favicon.ico HTTP/1.1" 404 -
127.0.0.1 - - [22/Oct/2026 08:43:16] "GET /workflows?feature=budgeting&limit=5 HTTP/1.1" 200 -
```

## Terminal 4 - Docker Compose

```
PS <repo>> docker compose down -v
 Container fraud-frontend-service Stopping
 Container smartbank-home Stopping
 Container loans-frontend-service Stopping
 Container budgeting-frontend-service Stopping
 Container smartbank-home Stopped
 Container smartbank-home Removing
 Container smartbank-home Removed
 Container fraud-frontend-service Stopped
 Container fraud-frontend-service Removing
 Container fraud-frontend-service Removed
 Container fraud-service Stopping
 Container budgeting-frontend-service Stopped
 Container budgeting-frontend-service Removing
 Container budgeting-frontend-service Removed
 Container budgeting-service Stopping
 Container loans-frontend-service Stopped
 Container loans-frontend-service Removing
 Container loans-frontend-service Removed
 Container loans-service Stopping
 Container fraud-service Stopped
 Container fraud-service Removing
 Container fraud-service Removed
 Container fraud-database-service Stopping
 Container budgeting-service Stopped
 Container budgeting-service Removing
 Container budgeting-service Removed
 Container budgeting-database-service Stopping
 Container transactions Stopping
 Container loans-service Stopped
 Container loans-service Removing
 Container loans-service Removed
 Container loans-database-service Stopping
 Container accounts Stopping
 Container transactions Stopped
 Container transactions Removing
 Container transactions Removed
 Container accounts Stopped
 Container accounts Removing
 Container accounts Removed
 Container fraud-database-service Stopped
 Container fraud-database-service Removing
 Container fraud-database-service Removed
 Container budgeting-database-service Stopped
 Container budgeting-database-service Removing
 Container budgeting-database-service Removed
 Container loans-database-service Stopped
 Container loans-database-service Removing
 Container loans-database-service Removed
 Volume smartbanking_loans-data Removing
 Volume smartbanking_budgets-data Removing
 Volume smartbanking_fraud-data Removing
 Network smartbank-network Removing
 Volume smartbanking_fraud-data Removed
 Volume smartbanking_budgets-data Removed
 Volume smartbanking_loans-data Removed
 Network smartbank-network Removed
PS <repo>> docker compose up --build -d
 Image smartbank-home:0.1 Building
 Image smartbank-loans-web:0.1 Building
 Image smartbank-budgeting-db:0.1 Building
 Image smartbank-fraud-web:0.1 Building
 Image smartbank-loans-api:0.1 Building
 Image smartbank-fraud-db:0.1 Building
 Image smartbank-accounts:0.1 Building
 Image smartbank-budgeting-web:0.1 Building
 Image smartbank-budgeting-api:0.1 Building
 Image smartbank-loans-db:0.1 Building
 Image smartbank-fraud-api:0.1 Building
 Image smartbank-transactions:0.1 Building
... (349 lines of BuildKit image-build steps, omitted; the images it built are listed next)
 Image smartbank-transactions:0.1 Built
 Image smartbank-budgeting-db:0.1 Built
 Image smartbank-budgeting-web:0.1 Built
 Image smartbank-fraud-web:0.1 Built
 Image smartbank-loans-web:0.1 Built
 Image smartbank-fraud-api:0.1 Built
 Image smartbank-budgeting-api:0.1 Built
 Image smartbank-home:0.1 Built
 Image smartbank-loans-db:0.1 Built
 Image smartbank-loans-api:0.1 Built
 Image smartbank-accounts:0.1 Built
 Image smartbank-fraud-db:0.1 Built
 Volume smartbanking_loans-data Creating
 Volume smartbanking_fraud-data Creating
 Network smartbank-network Creating
 Volume smartbanking_budgets-data Creating
 Volume smartbanking_budgets-data Creating
 Volume smartbanking_loans-data Creating
 Network smartbank-network Creating
 Volume smartbanking_fraud-data Creating
 Volume smartbanking_fraud-data Created
 Volume smartbanking_fraud-data Created
 Volume smartbanking_budgets-data Created
 Volume smartbanking_budgets-data Created
 Volume smartbanking_loans-data Created
 Volume smartbanking_loans-data Created
 Network smartbank-network Created
 Network smartbank-network Created
 Container budgeting-database-service Creating
 Container fraud-database-service Creating
 Container smartbank-home Creating
 Container transactions Creating
 Container loans-database-service Creating
 Container accounts Creating
 Container smartbank-home Created
 Container budgeting-database-service Created
 Container loans-database-service Created
 Container fraud-database-service Created
 Container accounts Created
 Container loans-service Creating
 Container loans-service Created
 Container loans-frontend-service Creating
 Container loans-frontend-service Created
 Container transactions Created
 Container budgeting-service Creating
 Container fraud-service Creating
 Container budgeting-service Created
 Container budgeting-frontend-service Creating
 Container fraud-service Created
 Container fraud-frontend-service Creating
 Container budgeting-frontend-service Created
 Container fraud-frontend-service Created
 Container budgeting-database-service Starting
 Container loans-database-service Starting
 Container smartbank-home Starting
 Container transactions Starting
 Container accounts Starting
 Container fraud-database-service Starting
 Container fraud-database-service Started
 Container budgeting-database-service Started
 Container loans-database-service Started
 Container smartbank-home Started
 Container accounts Started
 Container loans-database-service Waiting
 Container transactions Started
 Container budgeting-database-service Waiting
 Container fraud-database-service Waiting
 Container loans-database-service Healthy
 Container loans-service Starting
 Container fraud-database-service Healthy
 Container budgeting-database-service Healthy
 Container fraud-service Starting
 Container budgeting-service Starting
 Container loans-service Started
 Container loans-frontend-service Starting
 Container fraud-service Started
 Container fraud-frontend-service Starting
 Container budgeting-service Started
 Container budgeting-frontend-service Starting
 Container fraud-frontend-service Started
 Container loans-frontend-service Started
 Container budgeting-frontend-service Started
PS <repo>> docker compose ps
NAME                         IMAGE                         COMMAND                  SERVICE                      CREATED         STATUS                   PORTS
accounts                     smartbank-accounts:0.1        "python run.py"          accounts                     6 seconds ago   Up 5 seconds (healthy)   0.0.0.0:3001->3001/tcp, [::]:3001->3001/tcp, 0.0.0.0:5001->5001/tcp, [::]:5001->5001/tcp, 0.0.0.0:5011->5011/tcp, [::]:5011->5011/tcp
budgeting-database-service   smartbank-budgeting-db:0.1    "python app.py"          budgeting-database-service   7 seconds ago   Up 5 seconds (healthy)   0.0.0.0:5014->5014/tcp, [::]:5014->5014/tcp
budgeting-frontend-service   smartbank-budgeting-web:0.1   "/docker-entrypoint.…"   budgeting-frontend-service   6 seconds ago   Up Less than a second    0.0.0.0:3004->80/tcp, [::]:3004->80/tcp
budgeting-service            smartbank-budgeting-api:0.1   "python app.py"          budgeting-service            6 seconds ago   Up Less than a second    0.0.0.0:5004->5004/tcp, [::]:5004->5004/tcp
fraud-database-service       smartbank-fraud-db:0.1        "python app.py"          fraud-database-service       7 seconds ago   Up 5 seconds (healthy)   0.0.0.0:5013->5013/tcp, [::]:5013->5013/tcp
fraud-frontend-service       smartbank-fraud-web:0.1       "/docker-entrypoint.…"   fraud-frontend-service       6 seconds ago   Up Less than a second    0.0.0.0:3003->80/tcp, [::]:3003->80/tcp
fraud-service                smartbank-fraud-api:0.1       "python app.py"          fraud-service                6 seconds ago   Up Less than a second    0.0.0.0:5003->5003/tcp, [::]:5003->5003/tcp
loans-database-service       smartbank-loans-db:0.1        "python app.py"          loans-database-service       7 seconds ago   Up 5 seconds (healthy)   0.0.0.0:5012->5012/tcp, [::]:5012->5012/tcp
loans-frontend-service       smartbank-loans-web:0.1       "/docker-entrypoint.…"   loans-frontend-service       6 seconds ago   Up Less than a second    0.0.0.0:3002->80/tcp, [::]:3002->80/tcp
loans-service                smartbank-loans-api:0.1       "python app.py"          loans-service                6 seconds ago   Up Less than a second    0.0.0.0:5002->5002/tcp, [::]:5002->5002/tcp
smartbank-home               smartbank-home:0.1            "/docker-entrypoint.…"   home                         7 seconds ago   Up 5 seconds             0.0.0.0:3000->80/tcp, [::]:3000->80/tcp
transactions                 smartbank-transactions:0.1    "python run.py"          transactions                 6 seconds ago   Up 5 seconds             0.0.0.0:3005->3005/tcp, [::]:3005->3005/tcp, 0.0.0.0:5005->5005/tcp, [::]:5005->5005/tcp, 0.0.0.0:5015->5015/tcp, [::]:5015->5015/tcp
```

`docker compose ps` lists twelve services, and none of them is the MCP, RAG or Multi-Agent server: those three stay on the host, and the containers reach them at `host.docker.internal`.

## Terminal 5 - health checks

Every URL in the probe list of `tools/ci/deploy-remote.sh`, the MCP server's `tools/list` over JSON-RPC, and the Multi-Agent server's health.

| Service | Call | URL | Status |
|---|---|---|---|
| home | GET | http://localhost:3000/ | 200 |
| accounts-api | GET | http://localhost:5001/api/health | 200 |
| loans-api | GET | http://localhost:5002/api/health | 200 |
| fraud-api | GET | http://localhost:5003/api/health | 200 |
| budgeting-api | GET | http://localhost:5004/api/health | 200 |
| transactions-api | GET | http://localhost:5005/api/health | 200 |
| accounts-web | GET | http://localhost:3001/ | 200 |
| loans-web | GET | http://localhost:3002/tabs/loans.html | 200 |
| fraud-web | GET | http://localhost:3003/tabs/normal.html | 200 |
| budgeting-web | GET | http://localhost:3004/tabs/budgets.html | 200 |
| transactions-web | GET | http://localhost:3005/tabs/transactions.html | 200 |
| rag-server | GET | http://localhost:8200/health | 200 |
| multi-agent-server | GET | http://localhost:8300/health | 200 |
| mcp-server | POST `tools/list` | http://localhost:8100/mcp | 200 |

```
PS <repo>> # step 6: probe list from tools/ci/deploy-remote.sh, plus MCP tools/list and Multi-Agent health
home                 GET  http://localhost:3000/                        200
accounts-api         GET  http://localhost:5001/api/health              200
loans-api            GET  http://localhost:5002/api/health              200
fraud-api            GET  http://localhost:5003/api/health              200
budgeting-api        GET  http://localhost:5004/api/health              200
transactions-api     GET  http://localhost:5005/api/health              200
accounts-web         GET  http://localhost:3001/                        200
loans-web            GET  http://localhost:3002/tabs/loans.html         200
fraud-web            GET  http://localhost:3003/tabs/normal.html        200
budgeting-web        GET  http://localhost:3004/tabs/budgets.html       200
transactions-web     GET  http://localhost:3005/tabs/transactions.html  200
rag-server           GET  http://localhost:8200/health                  200
multi-agent-server   GET  http://localhost:8300/health                  200
mcp-server           POST http://localhost:8100/mcp                     200 tools/list: budgeting_summary, accounts_count, loans_list, fraud_alerts_count, transactions_spending

PS <repo>> docker compose ps --services
accounts
budgeting-database-service
budgeting-frontend-service
budgeting-service
fraud-database-service
fraud-frontend-service
fraud-service
loans-database-service
loans-frontend-service
loans-service
home
transactions
```

## Terminal 5 - the containers reach the host servers

The budgeting API runs in a container and calls the three host servers through `host.docker.internal`.

| Call | Result |
|---|---|
| `GET http://localhost:5004/api/health` | 200; `mcp`, `rag` and `multi_agent` all `enabled: true`, at `host.docker.internal` ports 8100, 8200 and 8300 |
| `GET http://localhost:5004/ui/mcp/status` | 200; Reachable, 5 tools |
| `GET http://localhost:5004/ui/rag/status` | 200; Reachable, 67 chunks, 9 documents, hybrid, gemini / gemini-flash-lite-latest |
| `GET http://localhost:5004/ui/multi-agent/status` | 200; Reachable, planner → worker → reviewer → human, 0 pending, auth open |

```
PS <repo>> # step 7: the budgeting container reaching the host servers
GET http://localhost:5004/api/health -> 200
{"llm":"gemini","mcp":{"enabled":true,"url":"http://host.docker.internal:8100/mcp"},"multi_agent":{"enabled":true,"url":"http://host.docker.internal:8300"},"rag":{"enabled":true,"url":"http://host.docker.internal:8200"},"service":"budgets-service","status":"running"}

GET http://localhost:5004/ui/mcp/status -> 200
<span class="badge badge-ok">Reachable</span> <code>http://host.docker.internal:8100/mcp</code> &middot; 5 tools: <span class="chip">budgeting_summary</span> <span class="chip">accounts_count</span> <span class="chip">loans_list</span> <span class="chip">fraud_alerts_count</span> <span class="chip">transactions_spending</span>
GET http://localhost:5004/ui/rag/status -> 200
<span class="badge badge-ok">Reachable</span> <code>http://host.docker.internal:8200</code> &middot; 67 chunks &middot; 9 documents &middot; hybrid &middot; gemini / gemini-flash-lite-latest
GET http://localhost:5004/ui/multi-agent/status -> 200
<span class="badge badge-ok">Reachable</span> <code>http://host.docker.internal:8300</code> &middot; planner &rarr; worker &rarr; reviewer &rarr; human &middot; 0 pending &middot; auth open
```

## Terminal 5 - Multi-Agent validation record

```
PS <repo>> python -m multi_agent_server.validate
========================================================================
  SmartBank Multi-Agent Server - terminal validation
  server:  http://localhost:8300
  commit:  78df53c
========================================================================
  PASS  1. server reachable
        call:      GET /health  
        expected:  service multi-agent-server with a four-stage pipeline
        observed:  HTTP 200; pipeline planner -> worker -> reviewer -> human; roles ['planner', 'worker', 'reviewer']; models {'planner': 'shared AI-Mode model', 'reviewer': 'shared AI-Mode model', 'worker': 'shared AI-Mode model'}; max_revisions 1
  PASS  2. full workflow reaches the human gate
        call:      POST /workflow + poll /status  {"feature": "budgeting", "request": "Which budget categories went over the limit in September 2026 and by how much?", "context": {"customer_id": 1, "month": 9, 
        expected:  planner, worker and reviewer complete; state awaiting_human_review with plan, evidence and review
        observed:  wf_5c90e33e -> awaiting_human_review; stages ['planner#1 completed 1.766s', 'worker#1 completed 1.344s', 'reviewer#1 completed 1.156s', 'human#1 running']; plan 2 tasks (model); evidence 1/1 ok; review accept (model)
  PASS  3. response withheld until a person decides
        call:      GET /workflow/<id>/response  {"workflow_id": "wf_5c90e33e"}
        expected:  HTTP 409 with awaiting_decision true; the workflow is listed under /workflows/pending
        observed:  HTTP 409: no response yet: the workflow has not been decided by a human; pending 1 incl. this one: True
  PASS  4. accept releases the final response
        call:      POST /workflow/<id>/decision  {"decision": "accept", "note": "", "by": "validate"}
        expected:  state accepted; GET /response is 200 with released true and the Worker's answer
        observed:  decision HTTP 200 -> accepted; response HTTP 200, released True, answer 210 chars, decided_by validate
  PASS  5. rejected workflow recorded, nothing released
        call:      POST /workflow, then decision reject  {"feature": "budgeting", "request": "What did I spend most on in September 2026, and is my overall budget on track?", "context": {"customer_id": 1, "month": 9, 
        expected:  state rejected; GET /response is 200 with released false and the note kept
        observed:  wf_06af6121 -> rejected; response HTTP 200, released False, answer None, note kept True
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
        observed:  wf_670b4eed -> failed; error: worker: no feature API answered: budgeting service unavailable: connection refused at http://127.0.0.1:9/api/budgets/summary - is the service running?
  PASS  9. coordination metrics computed from the audit files
        call:      GET /metrics  {"workflows": "wf_5c90e33e,wf_06af6121"}
        expected:  rates and stage times derived from the two JSONL files, covering the workflows above
        observed:  HTTP 200; workflows 2 (2 decided); plan acceptance 1.0, worker completion 1.0, handoff success 1.0, defect yield 0.0, rework 0.0, fallback 0.0, human acceptance 0.5; stage s {'human': 5.5, 'planner': 1.821, 'reviewer': 1.281, 'worker': 1.391}; end-to-end s {'to_decision': 10.0, 'to_human_gate': 4.5}
========================================================================
  9/9 checks passed, 0 skipped  (all three models took part)
========================================================================
exit code: 0
```

## Terminal 5 - one workflow from the terminal, decided by a person

The runner was started with its input closed, so it stopped at the human gate and printed the answer; the decision was then recorded with `review --id`.

```
PS <repo>> python -m multi_agent_server.run --feature budgeting --month 9 --year 2026 --request "How is my September 2026 budget tracking, and which categories are over?"
Started wf_2df0254b (budgeting) at http://localhost:8300; following the stages:
  planner  attempt 1  completed  1.735s  gemini / gemini-flash-lite-latest
  worker   attempt 1  completed  1.516s  gemini / gemini-flash-lite-latest
  reviewer attempt 1  completed  1.437s  gemini / gemini-flash-lite-latest

wf_2df0254b  budgeting  state awaiting_human_review  created 2026-10-21T21:14:44+00:00
  Request:  How is my September 2026 budget tracking, and which categories are over?
  Context:  {"customer_id": 1, "month": 9, "year": 2026}
  Plan:     Retrieve the September 2026 budget summary to determine budget tracking and identify
            over-budget categories. (2 tasks, source model, gemini / gemini-flash-lite-latest)
            t1 GET /api/budgets/summary {"customer_id": 1, "month": 9, "year": 2026}
            t2 analysis (after t1): Review the budget summary data from t1 to state how the September 2026 budget is tracking overall and explicitly list which categories are over-budget (status indicates over-budget or spend exceeds limit).
  Evidence: t1 http://localhost:5004/api/budgets/summary -> ok HTTP 200 0.031s
  Finding:  t2 <- t1: For September 2026, the overall budget is tracking with a total spent of
            1486.78 out of a total limit of 2160.0 (68.8% used), leaving a total remaining of
            673.22, with 2 out of 7 categories over budget by a total of 100.1.
  Finding:  t2 <- t1: The categories that are over budget are Dining Out (monthly limit 300.0,
            spent 325.2, status OVER_BUDGET, over by 25.2) and Shopping (monthly limit 400.0,
            spent 474.9, status OVER_BUDGET, over by 74.9).
  Answer:   Your September 2026 budget is tracking overall at 68.8% used, with a total spent of
            1486.78 against your total limit of 2160.0 and 673.22 remaining. Out of 7 budgeted
            categories, 2 are currently over budget. The categories that are over their limits
            are Dining Out (spent 325.2 against a 300.0 limit, going over by 25.2) and Shopping
            (spent 474.9 against a 400.0 limit, going over by 74.9). [source model, attempt 1]
  Review:   accept [source model, attempt 1, criteria met 3/3]
            The Worker successfully retrieved the September 2026 budget summary and accurately
            reported overall budget tracking and over-budget categories matching the API
            response.

  Awaiting your decision. The response is not released until you decide.
Decision  [A]ccept / [P]artially accept / [R]eject / [S]kip:   Please answer A, P, R or S (one of ['accept', 'partially_accept', 'reject'] or skip).
Decision  [A]ccept / [P]artially accept / [R]eject / [S]kip:   stopped: stdin is closed; use --decision, or run from an interactive terminal; decide later with: python -m multi_agent_server.review --id wf_2df0254b
exit code: 0
```

```
PS <repo>> python -m multi_agent_server.review --id wf_2df0254b --decision accept --note "figures match the September 2026 summary" --by "terminal:Bao"

wf_2df0254b  budgeting  state awaiting_human_review  created 2026-10-21T21:14:44+00:00
  Request:  How is my September 2026 budget tracking, and which categories are over?
  Context:  {"customer_id": 1, "month": 9, "year": 2026}
  Plan:     Retrieve the September 2026 budget summary to determine budget tracking and identify
            over-budget categories. (2 tasks, source model, gemini / gemini-flash-lite-latest)
            t1 GET /api/budgets/summary {"customer_id": 1, "month": 9, "year": 2026}
            t2 analysis (after t1): Review the budget summary data from t1 to state how the September 2026 budget is tracking overall and explicitly list which categories are over-budget (status indicates over-budget or spend exceeds limit).
  Evidence: t1 http://localhost:5004/api/budgets/summary -> ok HTTP 200 0.031s
  Finding:  t2 <- t1: For September 2026, the overall budget is tracking with a total spent of
            1486.78 out of a total limit of 2160.0 (68.8% used), leaving a total remaining of
            673.22, with 2 out of 7 categories over budget by a total of 100.1.
  Finding:  t2 <- t1: The categories that are over budget are Dining Out (monthly limit 300.0,
            spent 325.2, status OVER_BUDGET, over by 25.2) and Shopping (monthly limit 400.0,
            spent 474.9, status OVER_BUDGET, over by 74.9).
  Answer:   Your September 2026 budget is tracking overall at 68.8% used, with a total spent of
            1486.78 against your total limit of 2160.0 and 673.22 remaining. Out of 7 budgeted
            categories, 2 are currently over budget. The categories that are over their limits
            are Dining Out (spent 325.2 against a 300.0 limit, going over by 25.2) and Shopping
            (spent 474.9 against a 400.0 limit, going over by 74.9). [source model, attempt 1]
  Review:   accept [source model, attempt 1, criteria met 3/3]
            The Worker successfully retrieved the September 2026 budget summary and accurately
            reported overall budget tracking and over-budget categories matching the API
            response.
  -> accepted; response released
  Decision accept: response released at 2026-10-21T21:18:22+00:00 by terminal:Bao
  Answer:   Your September 2026 budget is tracking overall at 68.8% used, with a total spent of
            1486.78 against your total limit of 2160.0 and 673.22 remaining. Out of 7 budgeted
            categories, 2 are currently over budget. The categories that are over their limits
            are Dining Out (spent 325.2 against a 300.0 limit, going over by 25.2) and Shopping
            (spent 474.9 against a 400.0 limit, going over by 74.9).
  Correction: figures match the September 2026 summary
exit code: 0
```

```
PS <repo>> python -m multi_agent_server.review
Multi-Agent Server at http://localhost:8300 - 0 workflow(s) awaiting human review
exit code: 0
```

## Terminal 5 - agentic loop: the three Release 2 review modes

### multi_agent_review

The review covers the server's 8 latest workflows, and five of them predate this pass: `wf_7a3ca267` is an earlier UI test, `wf_80ebb1b9` is a 19 Oct test rejected as stale, and `wf_1c3b05d8`, `wf_29ea9179` and `wf_763e8ada` are the first pass on the old database.

```
PS <repo>> python agentic_loop.py --mode multi_agent_review

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
  [Multi-Agent Workflow Review] OBSERVE  8 workflow(s) from the running server's audit folder (multi_agent_server\data\audit): wf_7a3ca267 accepted (accept by budgeting-ui), wf_80ebb1b9 rejected (reject by terminal:Bao), wf_1c3b05d8 accepted (accept by validate), wf_29ea9179 rejected (reject by validate), wf_763e8ada rejected (reject by terminal:Bao), wf_5c90e33e accepted (accept by validate), wf_06af6121 rejected (reject by validate), wf_2df0254b accepted (accept by terminal:Bao). Stages planner 8/8, worker 8/8, reviewer 8/8, human 8/8; fallbacks 0; revisions 0. Decisions accept 4, partially_accept 0, reject 4, pending 0, failed 0. plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.50
  [Multi-Agent Workflow Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Multi-Agent Workflow Review] OBSERVE  answer accepted
  [Multi-Agent Workflow Review] REVIEW   second opinion from the review model

  --- multi_agent_review result ----------------------------------
  Evidence: 8 workflow(s) from the running server's audit folder (multi_agent_server\data\audit): wf_7a3ca267 accepted (accept by budgeting-ui), wf_80ebb1b9 rejected (reject by terminal:Bao), wf_1c3b05d8 accepted (accept by validate), wf_29ea9179 rejected (reject by validate), wf_763e8ada rejected (reject by terminal:Bao), wf_5c90e33e accepted (accept by validate), wf_06af6121 rejected (reject by validate), wf_2df0254b accepted (accept by terminal:Bao). Stages planner 8/8, worker 8/8, reviewer 8/8, human 8/8; fallbacks 0; revisions 0. Decisions accept 4, partially_accept 0, reject 4, pending 0, failed 0. plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.50

  Attempt 1 output:
    Workflows: 8 reviewed - wf_7a3ca267, wf_80ebb1b9, wf_1c3b05d8, wf_29ea9179, wf_763e8ada, wf_5c90e33e, wf_06af6121, wf_2df0254b
    Stages: planner 8/8, worker 8/8, reviewer 8/8, human 8/8; fallbacks 0; revisions 0
    Decisions: accept 4, partially_accept 0, reject 4; wf_7a3ca267 accept, wf_80ebb1b9 reject, wf_1c3b05d8 accept, wf_29ea9179 reject, wf_763e8ada reject, wf_5c90e33e accept, wf_06af6121 reject, wf_2df0254b accept
    Metrics: plan acceptance 1.00, worker completion 1.00, handoff success 1.00, human acceptance 0.50
    Recommendation: Keep the workflow stages and review process as they are since all stages completed successfully with zero fallbacks, zero revisions, and perfect completion and handoff metrics.
    Verdict: PASS - All 8 workflows completed their stages successfully with perfect plan acceptance, worker completion, and handoff success metrics.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: No evidence-backed risk identified.
    Correction: No correction required.
    Retest: Repeat validation after future changes.

  RESULT: PASS
  evidence: docs\evidence\multi_agent_review-20261021T211848Z.json
exit code: 0
```

### testing_review

```
PS <repo>> python agentic_loop.py --mode testing_review

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [Testing Report Review] PLAN     Review every student's pre-commit security report and post-commit endpoint test report and write the Testing Review entry from their figures
  [Testing Report Review]            - the reports under docs\testing follow the team naming convention (student-1 to student-5)
  [Testing Report Review]            - each pre-commit report names its scans with findings, fixed and accepted counts and a result
  [Testing Report Review]            - each post-commit report names the endpoints tested, their outcomes and the check count (or JUnit totals)
  [Testing Report Review]            - the entry quotes every scan name, count, outcome and the coverage exactly as the reports say
  [Testing Report Review]            - a failed report or a student without a report makes the verdict ATTENTION, never PASS
  [Testing Report Review] ACT      collecting evidence
  [Testing Report Review] OBSERVE  Pre-commit reports: student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; no pre-commit report: student-1, student-2, student-3, student-5. Post-commit reports: student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 31 checks); no post-commit report: student-1, student-2, student-5. Coverage 1 of 5 pre-commit, 2 of 5 post-commit; missing one or both: student-1, student-2, student-3, student-5; failed: none
  [Testing Report Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Testing Report Review] OBSERVE  answer accepted
  [Testing Report Review] REVIEW   second opinion from the review model

  --- testing_review result --------------------------------------
  Evidence: Pre-commit reports: student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; no pre-commit report: student-1, student-2, student-3, student-5. Post-commit reports: student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 31 checks); no post-commit report: student-1, student-2, student-5. Coverage 1 of 5 pre-commit, 2 of 5 post-commit; missing one or both: student-1, student-2, student-3, student-5; failed: none

  Attempt 1 output:
    Pre-commit: student-1 none; student-2 none; student-3 none; student-4 ruff-security 4/0/4 passed, detect-secrets 0/0/0 passed, pip-audit 7/7/0 passed; student-5 none
    Post-commit: student-1 none; student-2 none; student-3 14 tests 0 failures 0 errors (junit); student-4 GET /api/budgets/summary passed, POST /api/budgets passed (2/2 endpoints, 31 checks); student-5 none
    Coverage: 1 of 5 students have a pre-commit report, 2 of 5 have a post-commit report; missing: student-1, student-2, student-3, student-5
    Recommendation: The team must provide pre-commit and post-commit testing reports for student-1, student-2, and student-5, and pre-commit reports for student-3.
    Verdict: ATTENTION - Pre-commit and post-commit reports are missing for multiple students.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: No evidence-backed risk identified.
    Correction: No correction required.
    Retest: Repeat validation after future changes.

  RESULT: PASS
  evidence: docs\evidence\testing_review-20261021T211901Z.json
exit code: 0
```

### cloud_deployment_review

```
PS <repo>> python agentic_loop.py --mode cloud_deployment_review

========================================================================
  SmartBank - Shared Agentic Loop
  model: gemini / gemini-flash-lite-latest
========================================================================
  [Cloud Deployment Report Review] PLAN     Review the cloud deployment report and write the entry that supports the final human release decision
  [Cloud Deployment Report Review]            - the report names the provider, region, commit and the cloud-deployment.yml run
  [Cloud Deployment Report Review]            - every endpoint and CRUD check in the report returned its expected status
  [Cloud Deployment Report Review]            - AI-Mode, MCP, RAG and the Multi-Agent Server are all disabled in the baseline (the bonus profile may enable some)
  [Cloud Deployment Report Review]            - the entry quotes the provider, commit, counts, statuses and AI states exactly and records the human decision
  [Cloud Deployment Report Review]            - the release recommendation is approve only for a real deployment whose run succeeded, whose checks all passed, whose AI services match the profile and that has no open issue
  [Cloud Deployment Report Review] ACT      collecting evidence
  [Cloud Deployment Report Review] OBSERVE  azure australiaeast, commit 0000000, no cloud-deployment.yml run: 3 resources; endpoints 3/3 passed (home page 200, budgeting api health 200, budgets list 200); CRUD 3/3 passed (budget create 201, budget read 200, budget delete 200); baseline profile, AI services ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled; issues 0; recommendation hold (this is the sample report, not a real deployment; the report names no cloud-deployment.yml run); human decision pending
  [Cloud Deployment Report Review] ADAPT    degraded source - this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's real report is not in the repo yet, so nothing here describes a real deployment and the release is held
  [Cloud Deployment Report Review] ACT      asking gemini / gemini-flash-lite-latest (attempt 1)
  [Cloud Deployment Report Review] OBSERVE  answer accepted
  [Cloud Deployment Report Review] REVIEW   second opinion from the review model

  --- cloud_deployment_review result -----------------------------
  Evidence: azure australiaeast, commit 0000000, no cloud-deployment.yml run: 3 resources; endpoints 3/3 passed (home page 200, budgeting api health 200, budgets list 200); CRUD 3/3 passed (budget create 201, budget read 200, budget delete 200); baseline profile, AI services ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled; issues 0; recommendation hold (this is the sample report, not a real deployment; the report names no cloud-deployment.yml run); human decision pending
  DEGRADED: this is the sample report (docs/deployment/cloud-deployment-report.sample.json); the cloud owner's real report is not in the repo yet, so nothing here describes a real deployment and the release is held

  Attempt 1 output:
    Deployment: azure australiaeast, commit 0000000, workflow run none, 3 resources
    Endpoints: 3/3 passed - home page 200, budgeting api health 200, budgets list 200
    AI services: ai-mode disabled, mcp disabled, rag disabled, multi-agent disabled
    CRUD: 3/3 passed - budget create 201, budget read 200, budget delete 200
    Release recommendation: hold - Hold because this is the sample report, not a real deployment; the report names no cloud-deployment.yml run.
    Human decision: pending
    Verdict: ATTENTION - It is the sample report.
  OBSERVE: PASS

  REVIEW (gemini / gemini-flash-lite-latest):
    Risk: No evidence-backed risk identified.
    Correction: No correction required.
    Retest: Repeat validation after future changes.

  RESULT: PASS
  evidence: docs\evidence\cloud_deployment_review-20261021T211908Z.json
exit code: 0
```

## Terminal 5 - endpoint tests against the containerised budgeting API

`ENDPOINT_REPORT_DIR` was not set, so the committed reports under `docs/testing/` were not rewritten.

```
PS <repo>> $env:BUDGET_API_URL="http://localhost:5004"; python -m pytest services/budgeting/backend/budgeting_endpoint_tests -q -p no:cacheprovider
..                                                                       [100%]
2 passed in 0.29s
exit code: 0
```

## UI through the containers

Opened at http://localhost:3000, then Budgeting & Spending Insights, then its AI Mode tab (http://localhost:3004/tabs/ai-mode.html), with customer 1 and September 2026. Screenshots are in [docker-run-20261022/](docker-run-20261022/).

| Screenshot | What it shows |
|---|---|
| [terminals.png](docker-run-20261022/terminals.png) | terminals 1, 2, 3 and 5 side by side |
| [docker-compose-ps.png](docker-run-20261022/docker-compose-ps.png) | terminal 4: the end of `docker compose up --build -d` and the `docker compose ps` table |
| [home.png](docker-run-20261022/home.png) | the home page on port 3000 with the five feature cards |
| [budgeting-ai-mode.png](docker-run-20261022/budgeting-ai-mode.png) | the AI Mode tab: the MCP `budgeting_summary` result (7 budgets, $1,486.78 of $2,160.00, Dining Out and Shopping over) and the RAG grounded answer with its citation, each panel Reachable |
| [budgeting-multi-agent-decided.png](docker-run-20261022/budgeting-multi-agent-decided.png) | the Multi-Agent card for `wf_6956623d`: plan, evidence, findings, the Reviewer's accept, and the final response released by `budgeting-ui:Bao` |

The red text in terminals 2, 3 and 4 is PowerShell colouring stderr: Flask's development-server warning, its request log and docker compose's progress all go to stderr, so it does not mean a failure.

The human decisions, from `GET http://localhost:8300/workflows?feature=budgeting&limit=5`:

| Workflow | Source | State | Decided by | Note |
|---|---|---|---|---|
| `wf_6956623d` | UI | accepted | `budgeting-ui:Bao` | - |
| `wf_2df0254b` | terminal | accepted | `terminal:Bao` | figures match the September 2026 summary |
| `wf_06af6121` | validation run | rejected | `validate` | Validation run: rejected on purpose to record the withheld path. |
| `wf_5c90e33e` | validation run | accepted | `validate` | - |
| `wf_763e8ada` | terminal | rejected | `terminal:Bao` | made on an old local database, rerun after a reset |
