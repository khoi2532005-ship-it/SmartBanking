# Wiring a feature to the shared Multi-Agent Server

The shared Multi-Agent Server (`python -m multi_agent_server.server`, port 8300,
a host process, never a Compose service) runs Planner -> Worker -> Reviewer and
then waits for a person. Budgeting is wired to it; this page is the copy list
for the other features. Fraud has its own equivalent wiring (PR #57), so this
is mainly for accounts, loans and transactions.

Everything below lives in the budgeting feature and can be copied with the
feature name changed. Nothing in `multi_agent_server/` needs to change except
the catalogue entry for your feature.

## 1. Your endpoints in the catalogue

`multi_agent_server/catalogue.py` lists, per feature, the read-only endpoints
the Worker may call and the parameters it may pass. The Planner only ever
plans against this list and the contract rejects anything else. Each feature
already has one entry copied from its Release 1 MCP tool; add the endpoints
you want the Worker to use (path, parameter names, which are required, whether
`customer_id` is required). If an endpoint takes a period, name the parameters
`month` and `year` and set `translate_period: True` when the API wants
`date_from`/`date_to` instead (see transactions). Add a summariser in
`multi_agent_server/evidence.py` only if the default summary (counts and
scalar fields) is not enough.

## 2. The client

Copy `services/budgeting/backend/services/multi_agent_client.py` and set
`FEATURE`. It gives you: the `MULTI_AGENT_ENABLED` flag that short-circuits
before any network call, the 2 s connect timeout, the readable "start it
with python -m multi_agent_server.server" message, the bearer token
(`MULTI_AGENT_API_TOKEN`), the workflow-id check, `start`, `workflow_status`,
`workflow`, `decide`, `response`, `pending`, `status`, and `customer_view`.

Rule to keep: `customer_view(response(id))` is the only payload a customer may
see. `workflow(id)` carries the Worker's unreleased answer and the review and
is for the person doing the human review only.

## 3. The routes

Copy the Release 2 block at the end of `services/budgeting/backend/routes/agents.py`:

| Route | Who | Notes |
|---|---|---|
| `POST /api/multi-agent/workflows` | panel | needs the `HX-Request` or `X-Requested-With` header |
| `GET /api/multi-agent/workflows/<id>` | panel | poll: progress only (`customer_summary`), no reviewer name, note or error text |
| `GET /api/multi-agent/workflows/<id>/review-panel` | operator | plan, result, review |
| `POST /api/multi-agent/workflows/<id>/decision` | operator | `decision`, `note`, `reviewer`; recorded as `<feature>-ui:<reviewer>` |
| `GET /api/multi-agent/workflows/<id>/response` | customer | the customer view; 409 until decided |
| `GET /api/multi-agent/pending` | operator | your feature's pending workflows |

Keep the two guards: every POST needs the same-origin header, and when
`<FEATURE>_REVIEWER_TOKEN` is set the operator routes need `X-Reviewer-Token`.
Restrict CORS to your frontend origins the way `app.py` does. Add
`multi_agent` to `/api/health` and to `/api/agents/status`.

## 4. The fragments and the panel

Copy the Release 2 block at the end of `services/budgeting/backend/routes/ui.py`
and the two sections at the end of `services/budgeting/frontend/tabs/ai-mode.html`
(the panel and the review desk), plus the `htmx:configRequest` lines that add
the token header and the reviewer name. Budgeting keeps its AI panels on an AI
Mode tab next to the Normal tab, as the brief describes and as fraud and
accounts do. The customer card polls
`/ui/multi-agent/workflows/<id>/response`; the desk card polls itself.

## 5. Configuration

Compose already passes `MULTI_AGENT_ENABLED`, `MULTI_AGENT_SERVER_URL` and
`MULTI_AGENT_API_TOKEN` to every backend through the `x-llm-env` anchor. Add
the two defaults to your Dockerfile (`MULTI_AGENT_ENABLED=true`,
`MULTI_AGENT_SERVER_URL=http://host.docker.internal:8300`), pass your own
`<FEATURE>_REVIEWER_TOKEN` and `<FEATURE>_FRONTEND_ORIGINS` into your service's
compose block the way budgeting-service and fraud-service do (otherwise the desk
cannot be locked in Docker), and set `MULTI_AGENT_ENABLED: "false"` in your CI
jobs so no test ever calls the server.

## 6. Tests

Copy `tests/test_multi_agent_client.py` (stubbed transport: disabled,
unreachable, validation, customer view, guards) and
`tests/test_multi_agent_contract.py` (the real server app in process behind
your routes). Both run without a key, a server or the network. Add the status
fragment to your smoke probes and the panel needle to the frontend check.

## 7. Demo

```
python -m multi_agent_server.server                       # terminal 1
docker compose up --build -d                              # terminal 2
python -m multi_agent_server.run --feature <yours> --request "..." --customer 1
python -m multi_agent_server.review --watch 5             # decide from a terminal
python -m multi_agent_server.validate --evidence          # the test record
```
