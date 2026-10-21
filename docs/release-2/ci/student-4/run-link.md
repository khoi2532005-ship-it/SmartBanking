# Student 4 (Budgeting & Spending Insights): post-commit CI endpoint tests

A successful run of `student-4-budgets-ci` on PR #63:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39444432605

| | |
|---|---|
| Commit | `1aad0d6` (pull_request, 2026-10-21 UTC) |
| Jobs | Build images, Unit checks, Smoke check and endpoint tests, Evidence pack: all passed |
| Endpoint tests | 2 endpoint functions, 27 checks, 0 failures (step "Post-commit endpoint tests (GET /api/budgets/summary, POST /api/budgets)" of the smoke job) |
| Endpoints | `GET /api/budgets/summary` (the seeded period, its totals and statuses, three 400s) and `POST /api/budgets` (create, the new line in the summary, 409 on the duplicate, five 400s, cleanup) |
| AI integrations | MCP, RAG and the Multi-Agent Server switched off in CI, as the health answer confirms |
| Artifacts | `student-4-endpoint-tests` (the report in JSON and Markdown plus the JUnit XML), `student-4-report` |

The report the job writes is also kept in the repo as
`docs/testing/post-commit-endpoint-report-student-4.md` and `.json`, from a
run of the same tests against the same stack; the tests are in
`services/budgeting/backend/budgeting_endpoint_tests/`.
