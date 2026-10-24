# Student 4 (Budgeting & Spending Insights): post-commit CI endpoint tests

A successful run of `student-4-budgets-ci` on main after the last budgeting
change (PR #72) merged:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39725293520

| | |
|---|---|
| Commit | `fa227e0` (push to main, the merge of PR #72, 2026-10-22) |
| Attempt | 2, a re-run of the same commit at 05:19 UTC (attempt 1 at 04:58 UTC passed the same jobs). Every file here is from attempt 2 |
| Jobs | Build images, Unit checks, Smoke check, Evidence pack: all passed |
| Endpoint tests | both endpoint tests passed with every check (step "Post-commit endpoint tests (GET /api/budgets/summary, POST /api/budgets)" of the smoke job; the evidence pack's "Every gate passed" step reads the same result from the artifact) |
| Endpoints | `GET /api/budgets/summary` (the stored period must be exactly the `init_db.py` seed, the summary must match the backend logic on it, three 400s) and `POST /api/budgets` (create, the new line in the summary, 409 on the duplicate, five 400s, cleanup, gone again) |
| AI integrations | AI-Mode, MCP, RAG and the Multi-Agent Server switched off in CI, as the health answer confirms |

The run on PR #72 itself passed the same jobs:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39725131045

## Files

| File | What it is |
|---|---|
| `docs/testing/post-commit-endpoint-report-student-4.json` and `.md` | the endpoint test report from this run's `student-4-endpoint-tests` artifact (31 checks, all passed) |
| `student-4-endpoint-tests.xml` | the JUnit results from the same artifact |
| `student-4-endpoint-tests.log` | the log of the endpoint test step |
| `logs/build-images.log`, `logs/unit-checks.log`, `logs/smoke-check.log`, `logs/evidence-pack.log` | the full log of each job, from the run's log archive |

The tests are in `services/budgeting/backend/budgeting_endpoint_tests/`.
