# Pre-commit security report - Student 2 (Loans & Credit)

Run at commit `f5125cc` on `loans-and-credit` with
`pre-commit run --all-files` from the repository root,
2026-10-25T08:42:35Z. Every configured hook passed on the whole repository.
The report scope is the student-2 Loans & Credit feature, its workflow, and
the Azure deployment check: `services/loans`, `.github/workflows/student-2.yml`
and `deploy/azure/checks.py`. The report files are not part of the scanned
commit; run the hooks again when committing them.

| Scan | Result | Findings | Fixed | Accepted |
|---|---|---|---|---|
| ruff-security (`S`, `S101` ignored in test files only) | passed | 3 | 0 | 3 |
| detect-secrets (`.secrets.baseline`) | passed | 0 | 0 | 0 |
| pip-audit (loan backend and database requirements) | passed | 0 | 0 | 0 |

## Ruff security rules

The pinned Ruff version is 0.6.9. All three findings in the loan-service
scope are explicitly accepted with an inline `# noqa` and reason:

| Rule | Where | Why it is accepted |
|---|---|---|
| S104 bind to all interfaces | services/loans/backend/app.py:48 | the backend binds 0.0.0.0 so the API is reachable from the Docker network |
| S110 try-except-pass | services/loans/backend/routes/loans.py:228 | deleting repayments is best-effort rollback cleanup after a failed loan approval |
| S104 bind to all interfaces | services/loans/database/app.py:605 | the database service binds 0.0.0.0 so the backend can reach it through Docker |

The shared configuration ignores S101 in test files only; test assertions are
therefore not treated as findings.

## detect-secrets

The configured scan against `.secrets.baseline` passed with no new secrets
detected.

## pip-audit

The loan backend and database requirements hooks both passed with no reported
advisories. `pre-commit run --all-files` also passed the root, accounts,
budgeting, fraud and transactions pip-audit hooks.
