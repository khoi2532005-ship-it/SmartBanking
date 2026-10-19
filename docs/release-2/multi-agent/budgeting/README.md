# Budgeting - Release 2 Multi-Agent panel evidence

Captured on 2026-10-19 with headless Chrome driving the real AI Mode tab
(`services/budgeting/frontend/serve.py` on 3004, the budgeting, accounts and
transactions services on their ports, `python -m multi_agent_server.server`
on 8300, Gemini as the model). The panel is one card, as the fraud panel is:
the stages while it runs, then the plan, the evidence and findings, the
review, then the decision block inside the same card, then the final response.

| File | What it shows |
|---|---|
| `ui-strip.png` | the Normal / AI Mode strip at the top of the tab; neither tab carries its own SmartBank header any more |
| `ui-0-multi-agent-panel.png` | the panel before a start: status line, request form, example chips, and the history of earlier workflows |
| `ui-1-awaiting-decision.png` | the card at the gate: stage badges, plan, evidence, findings, answer, review, and the decision block (reviewer name, note, Accept / Partially accept (correct) / Reject) |
| `ui-2-released.png` | the same card after a partial accept: human completed, the final response released with the correction, decided by `budgeting-ui:Bao` |
| `ui-3-history.png` | the history list after the decision, with Open buttons that reload a card |
| `ui-4-rejected.png` | a second workflow rejected with a note: the final response is withheld, nothing is released |

The browser run (22 checks) also confirms that a double click on Start
creates one workflow, that Enter in the reviewer name box decides nothing,
that a double click on a decision button sends one decision, that the
decision posts the name, the note and the choice, that polling stops at the
gate, and that the history list refreshes itself when a workflow starts and
when it is decided. The same flow is checked without a browser in
`services/budgeting/backend/tests/test_multi_agent_client.py` (fragments,
stubbed server) and `tests/test_multi_agent_contract.py` (against the real
server app in process). The validation record for the server itself is under
`docs/evidence/`.
