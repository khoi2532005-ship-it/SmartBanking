# Budgeting - Release 2 Multi-Agent panel evidence

Captured on 2026-10-19 with headless Chrome driving the real AI Mode tab
(`services/budgeting/frontend/serve.py` on 3004, the budgeting, accounts and
transactions services on their ports, `python -m multi_agent_server.server`
on 8300, Gemini as the model, `BUDGET_REVIEWER_TOKEN` set on the API).

| File | What it shows |
|---|---|
| `ui-0-ai-mode-tab.png` | the AI Mode tab: the Normal / AI Mode strip, the period form and the top of the AI panels |
| `ui-1-customer-awaiting.png` | the customer card after Start: stage badges, then "Awaiting human review"; no plan, findings or review |
| `ui-2-review-desk.png` | the desk card for the waiting workflow: plan, evidence, findings, review and the decision form |
| `ui-3-customer-released.png` | the customer card after a partial accept: the released answer, the correction, the findings and the evidence endpoints |

The browser run also checks that a double click on Start creates one workflow, that Enter in
the note box decides nothing, that only the desk's requests carry the reviewer token and name,
and that the pending list refreshes itself after a decision. The same flow is checked in `services/budgeting/backend/tests/test_multi_agent_client.py`
(fragments) and `tests/test_multi_agent_contract.py` (against the real server
app). The validation record for the server itself is under `docs/evidence/`.
