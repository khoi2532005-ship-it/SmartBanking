# Cloud deployment results

Commit `e6f91a1`, 2026-10-24T07:03:54+00:00, run https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/40071955252.

AI services: ai_mode enabled, mcp enabled, rag enabled, multi_agent enabled.

| Check | Method | URL | Expected | Got | Result |
|---|---|---|---|---|---|
| home page | GET | https://home.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ | 200 | 200 | PASS |
| accounts page | GET | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ | 200 | 200 | PASS |
| accounts config | GET | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/config.js | 200 | 200 | PASS |
| accounts api health | GET | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/health | 200 | 200 | PASS |
| loans page | GET | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ | 200 | 200 | PASS |
| loans config | GET | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/config.js | 200 | 200 | PASS |
| loans api health | GET | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/health | 200 | 200 | PASS |
| fraud page | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/tabs/normal.html | 200 | 200 | PASS |
| fraud config | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/config.js | 200 | 200 | PASS |
| fraud api health | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/health | 200 | 200 | PASS |
| budgeting page | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/tabs/budgets.html | 200 | 200 | PASS |
| budgeting config | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/config.js | 200 | 200 | PASS |
| budgeting api health | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/health | 200 | 200 | PASS |
| budgeting ui fragment | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ui/budgets | 200 | 200 | PASS |
| transactions page | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ | 200 | 200 | PASS |
| transactions config | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/config.js | 200 | 200 | PASS |
| transactions api health | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/health | 200 | 200 | PASS |
| transactions ui fragment | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/ui/mcp/status | 200 | 200 | PASS |
| fraud mcp tools | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/mcp/tools | 200 | 200 | PASS |
| fraud mcp tool call | POST | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/mcp/tool | 200 | 200 | PASS |
| fraud rag query | POST | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rag/query | 200 | 200 | PASS |
| fraud multi-agent start | POST | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/agents/workflow | 202 | 202 | PASS |
| fraud multi-agent gate | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/agents/workflow/wf_33b7fcb4 | 200 | 200 | PASS |
| fraud multi-agent decision | POST | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/agents/workflow/wf_33b7fcb4/review | 200 | 200 | PASS |
| fraud multi-agent release | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/agents/workflow/wf_33b7fcb4 | 200 | 200 | PASS |
| accounts create | POST | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/customers | 201 | 201 | PASS |
| accounts read | GET | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/customers/9 | 200 | 200 | PASS |
| accounts update | PUT | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/customers/9 | 200 | 200 | PASS |
| accounts delete | DELETE | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/customers/9 | 200 | 200 | PASS |
| accounts read after delete | GET | https://accounts-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/customers/9 | 404 | 404 | PASS |
| loans create | POST | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/loans | 201 | 201 | PASS |
| loans read | GET | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/loans/4 | 200 | 200 | PASS |
| loans update | PUT | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/loans/4 | 200 | 200 | PASS |
| loans delete | DELETE | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/loans/4 | 200 | 200 | PASS |
| loans read after delete | GET | https://loans-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/loans/4 | 404 | 404 | PASS |
| fraud create | POST | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rules | 201 | 201 | PASS |
| fraud read | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rules/11 | 200 | 200 | PASS |
| fraud update | PUT | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rules/11 | 200 | 200 | PASS |
| fraud delete | DELETE | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rules/11 | 200 | 200 | PASS |
| fraud read after delete | GET | https://fraud-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/rules/11 | 404 | 404 | PASS |
| budgeting create | POST | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/budgets | 201 | 201 | PASS |
| budgeting read | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/budgets/15 | 200 | 200 | PASS |
| budgeting update | PUT | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/budgets/15 | 200 | 200 | PASS |
| budgeting delete | DELETE | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/budgets/15 | 200 | 200 | PASS |
| budgeting read after delete | GET | https://budgeting-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/budgets/15 | 404 | 404 | PASS |
| transactions create | POST | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/transactions | 201 | 201 | PASS |
| transactions read | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/transactions/32 | 200 | 200 | PASS |
| transactions update | PUT | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/transactions/32 | 200 | 200 | PASS |
| transactions delete | DELETE | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/transactions/32 | 200 | 200 | PASS |
| transactions read after delete | GET | https://transactions-frontend-service.icysand-2f0bb3f2.indonesiacentral.azurecontainerapps.io/api/transactions/32 | 404 | 404 | PASS |

## Issues

- none
