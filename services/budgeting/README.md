# Budgeting & Spending Insights

**Student 4 — Cong Bao Nguyen** · Release 0

Monthly budgets per spending category, tracked against real transaction data,
with AI-generated advice on what to adjust.

## Microservices

| Service | Port | Role |
|---|---|---|
| `budgets-frontend` | 3004 | HTMX UI (nginx in Docker, `serve.py` in dev) |
| `budgets-api` | 5004 | Business logic, cross-feature calls, AI-Mode |
| `budgets-db-api` | 5014 | Exclusive owner of `budgeting_and_insights.db` |

Request flow: **browser → budgets-frontend → budgets-api → budgets-db-api → SQLite**,
with `budgets-api` also calling the Transactions API and Ollama.

## Running it locally (no Docker)

From the repository root, in three terminals:

```powershell
# once
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r services\budgeting\backend\requirements.txt
.\.venv\Scripts\python.exe services\budgeting\database\init_db.py

# terminal 1 — database service
.\.venv\Scripts\python.exe services\budgeting\database\app.py

# terminal 2 — backend/API
.\.venv\Scripts\python.exe services\budgeting\backend\app.py

# terminal 3 — frontend
.\.venv\Scripts\python.exe services\budgeting\frontend\serve.py
```

Then open **http://localhost:3004/tabs/budgets.html**

## Running it with Docker Compose

```bash
docker compose build budgeting-database-service budgeting-service budgeting-frontend-service
docker compose up -d budgeting-database-service budgeting-service budgeting-frontend-service
docker compose down -v
```

## AI-Mode

The insight endpoints call the Gemini API through its OpenAI-compatible
chat-completions endpoint, using the same client shape as the other features.
Before demonstrating AI-Mode, put a key in `.env` at the repository root:

```bash
cp .env.example .env      # then set GEMINI_API_KEY=...
```

Configured with `LLM_PROVIDER` (default `gemini`), `GEMINI_API_KEY`,
`GEMINI_BASE_URL` and `GEMINI_MODEL` (default `gemini-flash-lite-latest`).
`LLM_PROVIDER=ollama` switches to a local model when the `local-llm`
compose profile is running.

When the key is missing or the provider is unreachable the endpoints return
**503** with an explanatory message; CRUD is unaffected.

## Cross-feature data: the Transactions API

Actual spending is read **only over HTTP** from the Transactions service
(Student 5). This feature never opens another feature's SQLite file.

`USE_MOCK_TRANSACTIONS` controls the fallback:

| Value | Behaviour |
|---|---|
| `auto` (default) | Try the Transactions API, fall back to mock data on failure |
| `true` | Always use mock data |
| `false` | Always use the live API, surface errors |

The mock dataset in [`backend/services/transactions_client.py`](backend/services/transactions_client.py)
covers customers 1–2 for August and September 2026, so the feature demos
standalone. Every response reports which source was used via `spending_source`,
and the UI states it beneath the table.

The client tolerates several plausible response shapes and field names
(`amount`/`transaction_amount`, `category`/`transaction_category`, …) because the
Transactions API contract is not final.

## Database

`budgeting_and_insights.db`, owned solely by `budgets-db-api`. Seeded at image
build time by `init_db.py`. The seeded budgets are a fixed demo period,
**September 2026** (plus three August lines for history): the tab defaults to
it, the CI smoke test names it, and the loop's budgeting mode falls back to it
when the current month is empty. API calls without `month`/`year` use the
current month and answer an empty month as empty.

| Table | Columns | Seeded |
|---|---|---|
| `budgets` | `budget_id`, `customer_id`, `category`, `monthly_limit`, `month`, `year`, `created_at` | 14 |
| `budget_insights` | `insight_id`, `budget_id` → `budgets`, `insight_text`, `generated_at`, `model_used` | 10 |
| `categories` | `category_id`, `name`, `description` | 10 |

## API

### Budgets (CRUD)

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/budgets` | List budgets (`customer_id`, `category`, `month`, `year`) |
| `GET` | `/api/budgets/summary` | Budgets + actual spend + over-budget flags |
| `GET` | `/api/budgets/<id>` | One budget with its spend and transactions |
| `POST` | `/api/budgets` | Create a budget |
| `PUT` | `/api/budgets/<id>` | Update limit, category or period |
| `DELETE` | `/api/budgets/<id>` | Delete a budget |
| `GET` | `/api/categories` | List spending categories |
| `GET` | `/api/transactions/spending` | What this feature reads from Transactions |

### AI-Mode

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/budgets/insight` | Insight across all budgets for a month |
| `POST` | `/api/budgets/<id>/explain` | Explain one category |
| `GET` | `/api/budgets/insights` | Stored insight history |
| `DELETE` | `/api/budgets/insights/<id>` | Delete a stored insight |

### Release 1: shared MCP and RAG servers

The frontend reaches the shared local servers only through this backend.
Both integrations are retained in the image and switched with env flags, so
CI runs with them disabled.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/agents/status` | Enabled/reachable state of both integrations, registered MCP tools |
| `GET` | `/api/mcp/tools` | `tools/list` relayed from the shared MCP server |
| `POST` | `/api/mcp/tool` | Invoke a read-only tool (`budgeting_summary` by default) and return its structured result |
| `POST` | `/api/rag/query` | Send a question to the shared RAG server, return the grounded answer contract |

`POST /api/mcp/tool` accepts `{"tool", "arguments"}` or, for this feature's
own tool, just `{"customer_id", "month", "year"}`. Only the five read-only
tools registered on the shared server may be named. A tool-level `isError`
comes back as HTTP 422 with the reason; a disabled or unreachable server as
503 with a message that says how to start it.

`POST /api/rag/query` relays the grounded answer as-is: `answer`,
`citations[]`, `confidence_category`, `retrieval_summary`,
`insufficient_context`. An insufficient-context answer is HTTP 200, because
it is a valid grounded response; the UI renders it as a distinct state.

| Variable | Default | Purpose |
|---|---|---|
| `MCP_ENABLED` | `true` | `false` makes MCP endpoints answer 503 without any network call. Compose passes it through; CI sets `false` |
| `MCP_SERVER_URL` | `http://localhost:8100/mcp` | Compose sets `http://host.docker.internal:8100/mcp` |
| `RAG_ENABLED` | `true` | `false` makes RAG endpoints answer 503 without any network call. Compose passes it through; CI sets `false` |
| `RAG_SERVER_URL` | `http://localhost:8200` | Compose sets `http://host.docker.internal:8200` |

The MCP client (`backend/services/mcp_client.py`) speaks JSON-RPC 2.0 over
plain HTTP to the stateless streamable-HTTP server, so the image carries no
MCP SDK. Checks: `python -m tests.test_agent_clients` from `backend/`.

### Release 2: shared Multi-Agent Server

The shared Multi-Agent Server (`python -m multi_agent_server.server`, port
8300) runs Planner -> Worker -> Reviewer and then waits for a person. This
backend is the only thing the frontend talks to; `backend/services/multi_agent_client.py`
is the typed client (flag, 2 s connect timeout, readable message with the
start command when the server is down, bearer token when one is configured).

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/multi-agent/workflows` | `{"request", "customer_id"?, "month"?, "year"?}` -> 202 summary. Needs the `HX-Request` or `X-Requested-With` header |
| `GET` | `/api/multi-agent/workflows` | The most recent budgeting workflows, newest first (history) |
| `GET` | `/api/multi-agent/workflows/<id>` | The whole workflow: stages, plan, Worker result, review, decision and final response (budgeting workflows only) |
| `POST` | `/api/multi-agent/workflows/<id>/decision` | `{"decision": accept \| partially_accept \| reject, "note"?, "reviewer"?}`. Recorded in the audit as `budgeting-ui:<reviewer>` |

Two boundaries: this feature acts only on its own workflows (another
feature's id is a 404 here), and every POST needs the same-origin marker
(`HX-Request`, which HTMX sends, or `X-Requested-With`), which a cross-site
form cannot set. CORS allows only the frontend origins (ports 3004 and 3000
on any host, plus `BUDGET_FRONTEND_ORIGINS`).

| Variable | Default | Purpose |
|---|---|---|
| `MULTI_AGENT_ENABLED` | `true` | `false` makes every Multi-Agent route answer 503 without any network call. Compose passes it through; CI sets `false` |
| `MULTI_AGENT_SERVER_URL` | `http://localhost:8300` | Compose sets `http://host.docker.internal:8300` |
| `MULTI_AGENT_API_TOKEN` | empty | Sent as a bearer token when the server requires one |
| `MULTI_AGENT_CLIENT_TIMEOUT` | `10` | Read timeout in seconds; every call answers quickly because the server runs the stages in the background |
| `BUDGET_FRONTEND_ORIGINS` | empty | Extra browser origins allowed by CORS, comma-separated |

Fragments: `GET /ui/multi-agent/status` (status line); `POST /ui/multi-agent/workflows`
(start) and `GET /ui/multi-agent/workflows/<id>` return the one card that
carries the whole workflow: it polls itself every 2 s while the stages run,
shows the plan, the evidence and findings, and the review with its risks, and
once the state is `awaiting_human_review` the decision block (reviewer name,
note, Accept / Partially accept / Reject) appears inside the same card.
`POST /ui/multi-agent/workflows/<id>/decision` returns the card with the
final response, released or withheld; `GET /ui/multi-agent/history` lists the
most recent budgeting workflows with an Open button each. The panel sits on
the AI Mode tab under the MCP and RAG panels. Checks:
`python -m tests.test_multi_agent_client` (stubbed transport) and
`python -m tests.test_multi_agent_contract` (the real server app, in process)
from `backend/`.

### HTMX fragments

The frontend has two tabs, as fraud and accounts do: `tabs/budgets.html`
(Normal: the period form, create a budget, budgets this period) and
`tabs/ai-mode.html` (AI Mode: AI insight, the MCP and RAG panels and the
Multi-Agent panel), linked by a tab strip. Neither tab carries its own
SmartBank header: the shared home page on port 3000 frames them.

`/ui/*` returns HTML fragments for the frontend to swap in. The `/api/*` JSON
endpoints are the contract other features consume. Release 1 adds two panels
to the tab, backed by `GET /ui/mcp/status`, `GET /ui/mcp/tools`,
`POST /ui/mcp/tool`, `GET /ui/rag/status` and `POST /ui/rag/query`: the
structured MCP tool result, and the grounded answer with citations and a
confidence badge or the distinct insufficient-context state. Each panel's
status line says whether its server is reachable, inactive (flag off) or
down, and the controls stay in place in every state.

## Budget status

| Status | Condition |
|---|---|
| `ON_TRACK` | Under 80% of limit |
| `NEAR_LIMIT` | 80%–100% of limit |
| `OVER_BUDGET` | Spent exceeds limit |

## Tests

```powershell
cd services\budgeting\backend
..\..\.venv\Scripts\python.exe -m tests.test_budget_logic
```

13 checks over the budget maths and the mock transactions client, plus
`tests.test_agent_clients` (MCP and RAG), `tests.test_multi_agent_client` and
`tests.test_multi_agent_contract` (Release 2) and `tests.test_budget_routes`.
All run in CI by `.github/workflows/student-4.yml`.

## Prompts

`prompts/budgeting/` — `insight_system.txt` (persona and rules),
`insight_task.txt` (monthly insight), `explain_task.txt` (single category).
Edit these to change AI behaviour; no code change needed.
