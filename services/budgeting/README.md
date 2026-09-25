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
build time by `init_db.py`.

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
| `MCP_ENABLED` | `true` | `false` makes MCP endpoints answer 503 without any network call |
| `MCP_SERVER_URL` | `http://localhost:8100/mcp` | Compose sets `http://host.docker.internal:8100/mcp` |
| `RAG_ENABLED` | `true` | `false` makes RAG endpoints answer 503 without any network call |
| `RAG_SERVER_URL` | `http://localhost:8200` | Compose sets `http://host.docker.internal:8200` |

The MCP client (`backend/services/mcp_client.py`) speaks JSON-RPC 2.0 over
plain HTTP to the stateless streamable-HTTP server, so the image carries no
MCP SDK. Checks: `python -m tests.test_agent_clients` from `backend/`.

### HTMX fragments

`/ui/*` returns HTML fragments for the frontend to swap in. The `/api/*` JSON
endpoints are the contract other features consume. Release 1 adds
`GET /ui/mcp/tools`, `POST /ui/mcp/tool` and `POST /ui/rag/query`, which
render the MCP tool result, and the grounded answer with citations and a
confidence badge or the insufficient-context state.

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

13 checks over the budget maths and the mock transactions client. Run in CI by
`.github/workflows/student-4.yml`.

## Prompts

`prompts/budgeting/` — `insight_system.txt` (persona and rules),
`insight_task.txt` (monthly insight), `explain_task.txt` (single category).
Edit these to change AI behaviour; no code change needed.
