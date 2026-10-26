# Pre-commit security report - Student 5 (Transactions)

Run at commit `6c97f6d` on `main` with
`pre-commit run --all-files` from the repository root,
2026-10-26T10:57:23Z. Every configured hook passed on the whole repository.
The report scope is the student-5 Transactions feature and its workflow:
`services/transactions` and `.github/workflows/student-5.yml`. The report
files are not part of the scanned commit; run the hooks again when committing them.

| Scan | Result | Findings | Fixed | Accepted |
|---|---|---|---|---|
| ruff-security (`S`, `S101` ignored in test files only) | passed | 5 | 0 | 5 |
| detect-secrets (`.secrets.baseline`) | passed | 0 | 0 | 0 |
| pip-audit (transactions backend and database requirements) | passed | 0 | 0 | 0 |

## Ruff security rules

The pinned Ruff version is 0.6.9. All five findings in the transactions-service
scope are explicitly accepted with an inline `# noqa` and reason:

| Rule | Where | Why it is accepted |
|---|---|---|
| S104 bind to all interfaces | services/transactions/backend/app.py:92 | the backend binds 0.0.0.0 so the API is reachable from the Docker network |
| S110 try-except-pass | services/transactions/backend/routes/transactions.py:80 | fallback category inference should never block transaction creation |
| S104 bind to all interfaces | services/transactions/database/app.py:290 | the database service binds 0.0.0.0 so the backend can reach it through Docker |
| S104 bind to all interfaces | services/transactions/frontend/server.py:41 | frontend must bind on all interfaces for container reachability |
| S603 subprocess call | services/transactions/run.py:44 | trusted local service launcher started from repo-managed paths |

The shared configuration ignores S101 in test files only; test assertions are
therefore not treated as findings.

## detect-secrets

The configured scan against `.secrets.baseline` passed with no new secrets
detected.

## pip-audit

The transactions backend and database requirements hooks both passed with no reported
advisories. `pre-commit run --all-files` also passed the root, accounts,
budgeting, fraud and loans pip-audit hooks.
