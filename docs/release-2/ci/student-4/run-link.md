# Student 4 (Budgeting & Spending Insights): post-commit CI endpoint tests

A successful run of `student-4-budgets-ci` on main, right after PR #63 merged:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39536382116

| | |
|---|---|
| Commit | `3110057` (push to main, the merge of PR #63, 2026-10-21 03:02 UTC) |
| Jobs | Build images, Unit checks, Smoke check, Evidence pack: all passed |
| Endpoint tests | both endpoint tests passed with every check (step "Post-commit endpoint tests (GET /api/budgets/summary, POST /api/budgets)" of the smoke job; the evidence pack's "Every gate passed" step reads the same result from the artifact) |
| Endpoints | `GET /api/budgets/summary` (the stored period must be exactly the `init_db.py` seed, the summary must match the backend logic on it, three 400s) and `POST /api/budgets` (create, the new line in the summary, 409 on the duplicate, five 400s, cleanup, gone again) |
| AI integrations | MCP, RAG and the Multi-Agent Server switched off in CI, as the health answer confirms |
| Artifacts | `student-4-endpoint-tests` (the report in JSON and Markdown plus the JUnit XML), `student-4-report` |

The last run on the PR itself, on `f33ee12`, passed the same jobs:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39535025221

The report kept in the repo, `docs/testing/post-commit-endpoint-report-student-4.md`
and `.json`, is from a local run of the same tests on `c47d729` against the same
stack (31 checks, all passed); the tests are in
`services/budgeting/backend/budgeting_endpoint_tests/`.
