# Budgeting & Spending Insights

**Student 4 — Cong Bao Nguyen** · Release 0

Monthly budgets per spending category, tracked against real transaction data,
with AI-generated advice on what to adjust.

## Microservices

| Service | Port | Role |
|---|---|---|
| `budgets-frontend` | 8030 | HTMX UI (nginx in Docker, `serve.py` in dev) |
| `budgets-api` | 5004 | Business logic, cross-feature calls, AI-Mode |
| `budgets-db-api` | 5014 | Exclusive owner of `budgeting_and_insights.db` |

Request flow: **browser → budgets-frontend → budgets-api → budgets-db-api → SQLite**,
with `budgets-api` also calling the Transactions API and Ollama.

## Running it locally (no Docker)

From the repository root, in three terminals:

```powershell
# once
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r budgeting-and-insights\backend\requirements.txt
.\.venv\Scripts\python.exe budgeting-and-insights\database\init_db.py

# terminal 1 — database service
.\.venv\Scripts\python.exe budgeting-and-insights\database\app.py

# terminal 2 — backend/API
.\.venv\Scripts\python.exe budgeting-and-insights\backend\app.py

# terminal 3 — frontend
.\.venv\Scripts\python.exe budgeting-and-insights\frontend\serve.py
```

Then open **http://localhost:8030/tabs/budgets.html**

## Running it with Docker Compose

```bash
docker compose -f docker-compose.budgets.yml build
docker compose -f docker-compose.budgets.yml up -d
docker compose -f docker-compose.budgets.yml down -v
```

## AI-Mode

The insight endpoints call Ollama directly (`POST /api/generate`). Before
demonstrating AI-Mode:

```bash
ollama serve
ollama pull qwen2.5:0.5b
```

Configured with `OLLAMA_URL` (default `http://localhost:11434`, `http://ollama:11434`
in Compose) and `OLLAMA_MODEL` (default `qwen2.5:0.5b`).

When Ollama is unreachable the endpoints return **503** with an explanatory
message; CRUD is unaffected.

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

### HTMX fragments

`/ui/*` returns HTML fragments for the frontend to swap in. The `/api/*` JSON
endpoints are the contract other features consume.

## Budget status

| Status | Condition |
|---|---|
| `ON_TRACK` | Under 80% of limit |
| `NEAR_LIMIT` | 80%–100% of limit |
| `OVER_BUDGET` | Spent exceeds limit |

## Tests

```powershell
cd budgeting-and-insights\backend
..\..\.venv\Scripts\python.exe -m tests.test_budget_logic
```

13 checks over the budget maths and the mock transactions client. Run in CI by
`.github/workflows/student-4.yml`.

## Prompts

`prompts/budgets/` — `insight_system.txt` (persona and rules),
`insight_task.txt` (monthly insight), `explain_task.txt` (single category).
Edit these to change AI behaviour; no code change needed.
