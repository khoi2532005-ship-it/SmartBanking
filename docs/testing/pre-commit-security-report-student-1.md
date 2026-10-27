# Pre-commit security report - Student 1 (Accounts & Customers)

Run at commit `46f3539` on `precommit-demo` with
`pre-commit run --all-files` from the repository root,
2026-10-27T16:05:49Z. All three hooks passed on the scope I own:
services/accounts and agentic/modes/accounts.py. A second commit on the
same branch, carrying a planted dummy AWS key, was refused before
anything entered history — Ruff's S rules flagged the assignment (S105)
and detect-secrets flagged the values — the file was removed, and git log
still shows only the clean commit.

| Scan | Scope | Findings | Outcome |
|---|---|---|---|
| Ruff security, the S ruleset | services/accounts, agentic/modes/accounts.py | 0 | Nothing to resolve |
| Detect-secrets with .secrets.baseline | Every file staged by the commit | 0 | Nothing to resolve. The planted dummy key was blocked and removed |
| Pip-audit | services/accounts/backend/requirements.txt, services/accounts/database/requirements.txt | 0 | Nothing to resolve |
