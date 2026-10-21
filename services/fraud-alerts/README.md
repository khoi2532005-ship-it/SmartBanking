# Fraud Alerts - instructions

Owner: Khoi (student 3). Fraud Alerts flags suspicious transactions with
configurable rules, lets an analyst review each alert, and explains alerts in
plain English. Release 1 adds the shared MCP and RAG servers; Release 2 adds the
shared Multi-Agent Server with a human decision.

| Microservice | Compose service | Port | Code |
|---|---|---|---|
| Database (SQLite behind a small API) | `fraud-database-service` | 5013 | `database/` |
| Backend API | `fraud-service` | 5003 | `backend/` |
| Frontend (Normal and AI Mode tabs, nginx) | `fraud-frontend-service` | 3003 | `frontend/templates/tabs/` |

The backend also reads Accounts (5001) and Transactions (5005). AI-Mode, MCP
(8100), RAG (8200) and the Multi-Agent Server (8300) run on the host, never in
Docker.

## 1. Run it locally

From the repository root, with Python 3.12 and Docker Desktop:

```bash
cp .env.example .env                       # then set GEMINI_API_KEY
py -3.12 -m venv .venv                     # macOS: python3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1               # macOS: source .venv/bin/activate
pip install -r requirements-agentic.txt -r requirements-mcp.txt -r requirements-rag.txt -r requirements-multi-agent.txt
```

Then one terminal per server, in this order:

| Terminal | Command | Check |
|---|---|---|
| 1 | `python -m mcp_server.server` | the terminal shows it listening on 8100 (`/mcp` answers POST only) |
| 2 | `python -m rag_server.server` | http://localhost:8200/health |
| 3 | `python -m multi_agent_server.server` | http://localhost:8300/health |
| 4 | `docker compose up --build -d` | `docker compose ps` |

Open http://localhost:3003/tabs/normal.html (or the Fraud tab on the home page,
http://localhost:3000). http://localhost:5003/api/health shows which AI
integrations are switched on.

Fraud only, no AI servers: `docker compose up -d --build fraud-database-service fraud-service fraud-frontend-service`.

**Cloud (Azure Container Apps).** Only `fraud-frontend-service` is public. The
tabs read `/config.js`, which switches on cloud mode, and call their own
address; nginx forwards `/api/` to fraud-service, which is internal. Local runs
are unchanged. The runbook is `docs/deployment/container-apps.md`. The CRUD
check there is `FRAUD_API_URL=https://fraud-frontend-service.<domain> python -m pytest services/fraud-alerts/backend/tests/post_commit -v`.

## 2. Use the feature

**Normal tab** (CRUD, no AI):

1. **Alert Rules**: add a rule (for example "Large Transaction Alert", type
   `amount_over`, threshold 5000), enable, disable or delete it.
2. **Detection**: Run Detection evaluates every enabled rule against the
   transactions and stores the alerts it finds.
3. **Alert Dashboard**: filter alerts by status, amount range, date range or
   recipient/category and sort them; open one in Alert Detail, update its status
   (`new`, `reviewed`, `dismissed`, `confirmed`) or delete it.

**AI Mode tab**:

| Panel | Server | What to do |
|---|---|---|
| Explain a Flagged Transaction | AI-Mode (Gemini) | Enter an alert id, click Explain |
| Alert Summary | MCP | Pick a customer and status, click Count alerts; Registered tools lists the MCP tools |
| Ask about Fraud Alerts | RAG | Ask a question or click a chip; answers cite the corpus. The "off-topic question" chip shows the refusal |
| Multi-Agent Review | Multi-Agent Server | Pick a chip, Start workflow, watch Plan, Worker and Review fill, then decide |

In Multi-Agent Review nothing is released until a person decides. Enter your
name, then choose Accept, Partially accept (needs a correction note) or Reject.
History lists earlier workflows. Every stage and decision is written to the
server's audit files.

## 3. Multi-Agent workflow from the terminal

With terminals 1 to 4 running:

```bash
python -m multi_agent_server.run --feature fraud --customer 1 \
    --request "Summarise this customer's fraud alerts by severity and status."
```

It prints Planner, Worker and Reviewer as they finish, then asks for the
decision (`--decision accept|partially_accept|reject` skips the prompt).

## 4. API

Base URL http://localhost:5003. Browsers may call it only from the fraud tab
on the same host; add other origins in `FRAUD_FRONTEND_ORIGINS`.

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Service status and the four AI flags |
| `GET`, `POST /api/rules` | List (filters) or create rules |
| `GET`, `PUT`, `DELETE /api/rules/<id>` | Read, update, delete a rule |
| `POST /api/detection/run` | Run every enabled rule, store new alerts |
| `GET`, `POST /api/alerts` | List (filters) or create alerts |
| `GET`, `PUT`, `DELETE /api/alerts/<id>` | Read, update status, delete an alert |
| `GET /api/ai/alerts/<id>/explain` | AI-Mode explanation of one alert |
| `GET /api/mcp/tools`, `POST /api/mcp/tool` | MCP tools list and call |
| `POST /api/rag/query` | Ask the RAG server |
| `POST /api/agents/workflow` | Start a Multi-Agent workflow |
| `GET /api/agents/workflow/<id>` | Workflow state |
| `POST /api/agents/workflow/<id>/review` | Human decision |
| `GET /api/agents/workflows` | Workflow history |

Allowed values: rule types `amount_over`, `velocity`, `unusual_time`,
`new_recipient_high_value`; severities `low`, `medium`, `high`.

## 5. Configuration

Set in `.env`; `docker-compose.yml` passes them to `fraud-service`.

| Variable | Default | Meaning |
|---|---|---|
| `AI_MODE_ENABLED` | `true` | Explain panel and its LLM calls |
| `MCP_ENABLED`, `MCP_SERVER_URL` | `true`, host 8100 | Alert Summary panel |
| `RAG_ENABLED`, `RAG_SERVER_URL` | `true`, host 8200 | Ask panel |
| `MULTI_AGENT_ENABLED`, `MULTI_AGENT_SERVER_URL`, `MULTI_AGENT_API_TOKEN` | `true`, host 8300, empty | Multi-Agent Review panel |
| `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL` | `gemini` | Model used by AI-Mode (`ollama` for the local fallback) |
| `TRANSACTIONS_SOURCE` | `seed` | `seed` reads the built-in fixture; `http` reads the Transactions service |
| `FRAUD_FRONTEND_ORIGINS` | empty | Extra browser origins, e.g. a cloud frontend |

A flag set to `false` turns that panel off with a message; the rest of the
feature keeps working. CI and the cloud baseline run with all four set to
`false`.

## 6. Tests

Unit tests (no Docker, no API key):

```bash
pip install -r requirements-multi-agent.txt -r services/fraud-alerts/backend/requirements.txt pytest
cd services/fraud-alerts/backend
python -m pytest tests/unit -q
```

Post-commit endpoint tests run against a live backend, never in-process. They
cover two endpoint functions: `GET /api/alerts` with its filters, and
`POST /api/rules` through create, read, update and delete.

```bash
docker compose up -d --build --no-deps fraud-database-service fraud-service
FRAUD_API_URL=http://localhost:5003 python -m pytest services/fraud-alerts/backend/tests/post_commit -v
```

Point `FRAUD_API_URL` at the deployed backend to reuse the same suite as the
cloud CRUD check. The read tests do not assume freshly seeded data. They
plant their own disabled `release-check …` rule and alerts on customer 999999,
remove them afterwards, and first remove anything an interrupted run left
behind.

## 7. Pre-commit security

Once, from the repository root:

```bash
pip install pre-commit
pre-commit install --install-hooks
pre-commit run --files $(git ls-files services/fraud-alerts)
```

Every `git commit` then runs Ruff security rules (`S`), detect-secrets against
`.secrets.baseline`, and pip-audit over the fraud backend and database
requirements.

## 8. CI: `.github/workflows/student-3.yml`

Runs on pushes and pull requests to `main` that touch fraud files:

1. **Build images**: validates the compose file and builds the three fraud images.
2. **Unit checks**: agentic-loop engine tests, fraud unit tests (JUnit
   artifact `student-3-unit-tests`), non-empty prompt files.
3. **Smoke check**: starts the stack with every AI flag off and probes each endpoint.
4. **Endpoint tests**: the post-commit suite above (artifact `student-3-endpoint-tests`).
5. **Evidence pack**: a run-linked report.

## 9. Agentic loop

```bash
python agentic_loop.py --mode fraud
```

Runs Plan, Act, Observe, Adapt over the fraud API and appends evidence to
`docs/evidence/`.

## 10. Evidence

| Evidence | Location |
|---|---|
| Multi-Agent terminal run, UI screenshots, audit JSONL | `docs/release-2/multi-agent/fraud/` |
| CI endpoint-test run link, JUnit XML, log | `docs/release-2/ci/student-3/` |
| Local AI Mode tab with all four panels answering | `docs/release-2/deployment/local/fraud-ai-mode.png` |

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| A panel says its server is not running | Start that server's terminal (section 1) |
| "host.docker.internal could not be resolved" | On Linux the service needs `extra_hosts: ["host.docker.internal:host-gateway"]` |
| Browser blocks calls to 5003 (CORS) | Open the tab from port 3003 on the same host, or add the page origin to `FRAUD_FRONTEND_ORIGINS` |
| Cloud: every write answers 403 | `FRAUD_FRONTEND_ORIGINS` on fraud-service must be the frontend's own address (`deploy/azure/apps.json`) |
| `503 fraud-database-service unavailable` | `docker compose ps`; restart `fraud-database-service` |
| Workflow response returns 409 | Expected: the human decision has not been made yet |
| Windows asks to allow Python on 8100, 8200 or 8300 | Allow it, or the containers cannot reach the host servers |
