# Student 3 (Fraud Alerts): post-commit CI endpoint tests

A successful run of `student-3-fraud-ci` on PR #57:
https://github.com/khoi2532005-ship-it/SmartBanking/actions/runs/39147497832

| | |
|---|---|
| Commit | `f8d6bf4` (pull_request, 2026-10-18 16:59 UTC) |
| Jobs | Build images, Unit checks, Smoke check, Endpoint tests, Evidence pack: all passed |
| Endpoint tests | 14 tests, 0 failures, 0 errors, 0 skipped |
| Endpoints | `GET /api/alerts` (read) and the `POST /api/rules` create → read → update → delete cycle (write) |
| AI integrations | AI-Mode, MCP, RAG and Multi-Agent switched off in CI |

Both files below were downloaded from the run's `student-3-endpoint-tests` artifact:
- `student-3-endpoint-tests.xml`: the JUnit results
- `student-3-endpoint-tests.log`: the `pytest -v` output
