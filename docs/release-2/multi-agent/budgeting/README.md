# Budgeting - Release 2 Multi-Agent panel evidence

Captured on 2026-10-19 with headless Chrome driving the real Budgets tab
(`services/budgeting/frontend/serve.py` on 3004, the budgeting, accounts and
transactions services on their ports, `python -m multi_agent_server.server`
on 8300, Gemini as the model, `BUDGET_REVIEWER_TOKEN` set on the API).

| File | What it shows |
|---|---|
| `ui-1-customer-awaiting.png` | the customer card after Start: stage badges, then "Awaiting human review"; no plan, findings or review |
| `ui-2-review-desk.png` | the review desk opened with the reviewer token and name: the pending list and the desk card with the decision form |
| `ui-3-customer-released.png` | the customer card after a partial accept: the released answer, the correction, the findings and the evidence endpoints |

The same flow is checked in `services/budgeting/backend/tests/test_multi_agent_client.py`
(fragments) and `tests/test_multi_agent_contract.py` (against the real server
app). The validation record for the server itself is under `docs/evidence/`.
