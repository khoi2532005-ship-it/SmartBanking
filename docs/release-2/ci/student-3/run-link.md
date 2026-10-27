# Student 3 (Fraud Alerts): post-commit CI endpoint tests

A successful run of `student-3-fraud-ci` on `main`:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/40203858561

| | |
|---|---|
| Commit | `6c97f6d` (push to main, 2026-10-25 14:47 UTC) |
| Jobs | Build images, Unit checks, Smoke check, Endpoint tests, Evidence pack: all passed |
| Endpoint tests | 26 tests, 0 failures, 0 errors, 0 skipped |
| Endpoints | `GET /api/alerts` with its filters (read) and the `POST /api/rules` create → read → update → delete cycle (write) |
| AI integrations | AI-Mode, MCP, RAG and Multi-Agent switched off in CI |

Both files below were downloaded from the run's `student-3-endpoint-tests` artifact:
- `student-3-endpoint-tests.xml`: the JUnit results
- `student-3-endpoint-tests.log`: the `pytest -v` output

The same results as a report: `docs/testing/post-commit-endpoint-report-student-3.md`
(and `.json`, which the agentic loop's Testing Review reads).
