# Wiring a feature to the shared Multi-Agent Server

The shared Multi-Agent Server (`python -m multi_agent_server.server`, port 8300,
a host process, never a Compose service) runs Planner -> Worker -> Reviewer and
then waits for a person. Budgeting is wired to it; this page is the copy list
for the other features. Fraud has its own equivalent wiring (PR #57), so this
is mainly for accounts, loans and transactions.

Everything below lives in the budgeting feature and can be copied with the
feature name changed. Nothing in `multi_agent_server/` needs to change except
the catalogue entry for your feature: the server's `GET /workflows` already
takes `?feature=`, `?customer_id=` and `?limit=`, which is what a panel's
history list calls.

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
`workflow`, `decide`, `history` and `status`.

## 3. The routes

Copy the Release 2 block at the end of `services/budgeting/backend/routes/agents.py`:

| Route | Notes |
|---|---|
| `POST /api/multi-agent/workflows` | start; needs the `HX-Request` or `X-Requested-With` header |
| `GET /api/multi-agent/workflows[?customer_id=]` | your feature's latest workflows, newest first, one customer's when asked |
| `GET /api/multi-agent/workflows/<id>` | the whole workflow: stages, plan, result, review, decision, final response |
| `POST /api/multi-agent/workflows/<id>/decision` | `decision`, `note`, `reviewer`; recorded as `<feature>-ui:<reviewer>` |

Keep the two boundaries: every POST needs the same-origin header, and another
feature's workflow id is a 404. Answer browsers only from your own tab and the
home page on the same host as the API, the way `app.py` does (the same rule
fraud-service uses); `<FEATURE>_FRONTEND_ORIGINS` adds exact origins. Add
`multi_agent` to `/api/health` and to `/api/agents/status`.

## 4. The fragments and the panel

Copy the Release 2 block at the end of `services/budgeting/backend/routes/ui.py`
and the Multi-Agent section of `services/budgeting/frontend/tabs/ai-mode.html`.
The panel is one card, as fraud's is: Start, the stage badges while the card
polls itself every 2 s, then the plan, the evidence and findings, the review
with its risks, then the decision block (reviewer name, note, Accept /
Partially accept / Reject) inside the same card once the workflow is
awaiting human review, then the final response, released or withheld. A
refused or failed decision shows its reason inside the block and keeps the
typed note; a decision that went through replaces the card (HX-Retarget, so
expose it through CORS). A History list under the card shows the selected
customer's workflows and reopens them. Budgeting keeps its AI panels on an AI
Mode tab next to the Normal tab, as fraud and accounts do.

## 5. Configuration

Compose already passes `MULTI_AGENT_ENABLED`, `MULTI_AGENT_SERVER_URL` and
`MULTI_AGENT_API_TOKEN` to every backend through the `x-llm-env` anchor. Add
the two defaults to your Dockerfile (`MULTI_AGENT_ENABLED=true`,
`MULTI_AGENT_SERVER_URL=http://host.docker.internal:8300`), pass your own
`<FEATURE>_FRONTEND_ORIGINS` into your service's compose block if your page is
served from somewhere other than its own port, and set
`MULTI_AGENT_ENABLED: "false"` in your CI jobs so no test ever calls the server.

## 6. Tests

Copy `tests/test_multi_agent_client.py` (stubbed transport: disabled,
unreachable, validation, the card and the decision block, the history) and
`tests/test_multi_agent_contract.py` (the real server app in process behind
your routes). Both run without a key, a server or the network. Add the status
and history fragments to your smoke probes and the panel needle to the
frontend check.

## 7. Demo

```
python -m multi_agent_server.server                       # terminal 1
docker compose up --build -d                              # terminal 2
python -m multi_agent_server.run --feature <yours> --request "..." --customer 1
python -m multi_agent_server.review --watch 5             # decide from a terminal
python -m multi_agent_server.validate --evidence          # the test record
```
