# Smart Banking App 
## A personal finance and banking assistant
 SmartBank is a personal finance and banking assistant where each student owns one full-stack feature (frontend + API + SQLite CRUD) with an Ollama LLM layer on top. The features are Accounts & Customers (plain-English summaries and risk profiles), Transactions (auto-categorisation and unusual-spend flags), Budgeting (actual vs budget advice), Loans & Credit (explainable eligibility and repayment options), and Fraud Alerts (human-readable explanations of suspicious transactions pulled via the Transactions API). Design references: Up Bank, Frollo, Revolut, Cleo, and CommBank's Smart Alerts.

## Repository layout

```
services/
  accounts/       Accounts & Customers  (William)  frontend + backend + database
  transactions/   Transactions          (Aidan)    frontend + backend + database
  fraud-alerts/   Fraud Alerts          (Khoi)     frontend + backend + database
  budgeting/      Budgeting & Insights  (Bao)      frontend + backend + database
  loans/          Loans & Credit        (David)    frontend + backend + database
shared/frontend/  Unified index.html, shared CSS theme, htmx
prompts/          Prompt files per feature (prompts/<feature>/) and agentic-loop prompts
agentic/          Shared agentic-loop engine; one mode per feature in agentic/modes/
tests/            Engine tests (no services or API key needed)
docs/             Feature registrations (features.md), loop guide (agentic-loop.md),
                  run evidence (evidence/)
agentic_loop.py   Plan -> Act -> Observe -> Adapt loop (run from the repo root)
```

## Run the whole app

```bash
cp .env.example .env          # then set GEMINI_API_KEY
docker compose up --build -d  # all five features + home page
docker compose ps
```

Open http://localhost:3000 for the shared home page. Feature frontends: accounts 3001,
loans 3002, transactions 3005, fraud alerts 3003, budgeting 3004. Backends on 5001-5005,
database services on 5011-5015.

Fallback local LLM: `docker compose --profile local-llm up -d` and set
`LLM_PROVIDER=ollama` in `.env`.

Stop everything: `docker compose down -v`

## Run the agentic loop

The shared `Plan -> Act -> Observe -> Adapt` workflow for the whole application
(project spec 4.3). Each feature is a mode on one menu, so every student demos
their own slice of the same loop.

```bash
pip install -r requirements-agentic.txt
python agentic_loop.py                 # menu - use this to demo
python agentic_loop.py --mode fraud    # one feature
python agentic_loop.py --all --quiet   # CI; exit code only
```

Runs append evidence to `docs/evidence/` for the technical report.

**Adding your feature:** copy `agentic/modes/_template.py`, implement four
methods, register it in `agentic/modes/__init__.py`. Full guide in
[docs/agentic-loop.md](docs/agentic-loop.md); `agentic/modes/fraud.py` is a
worked example.

```bash
python -m pytest tests/ -q             # engine tests, no services needed
```
