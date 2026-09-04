# Smart Banking App 
## A personal finance and banking assistant
 SmartBank is a personal finance and banking assistant where each student owns one full-stack feature (frontend + API + SQLite CRUD) with an Ollama LLM layer on top. The features are Accounts & Customers (plain-English summaries and risk profiles), Transactions (auto-categorisation and unusual-spend flags), Budgeting (actual vs budget advice), Loans & Credit (explainable eligibility and repayment options), and Fraud Alerts (human-readable explanations of suspicious transactions pulled via the Transactions API). Design references: Up Bank, Frollo, Revolut, Cleo, and CommBank's Smart Alerts.

## Repository layout

```
services/
  accounts/       Accounts & Customers  (William)  frontend + backend + database
  transactions/   Transactions          (Aidan)    ASP.NET solution
  fraud-alerts/   Fraud Alerts          (Khoi)     frontend + backend + database
  budgeting/      Budgeting & Insights  (Bao)      frontend + backend + database
  loans/          Loans & Credit        (David)    frontend + backend + database
shared/frontend/  Unified index.html, shared CSS theme, htmx
prompts/          Prompt files per feature (prompts/<feature>/) and agentic-loop prompts
docs/             Project spec (smartbank-spec.md), feature registrations (features.md)
agentic_loop.py   Plan -> Act -> Observe -> Adapt loop (run from the repo root)
docker-compose.budgets.yml   Standalone stack for the budgeting feature
```

## Run the whole app

```bash
cp .env.example .env          # then set GEMINI_API_KEY
docker compose up --build -d  # all five features + home page
docker compose ps
```

Open http://localhost:3000 for the shared home page. Feature frontends: accounts 3001,
loans and transactions 3002, fraud alerts 3003, budgeting 3004. Backends on 5001-5005
(transactions API on 5260), database services on 5011-5015.

Fallback local LLM: `docker compose --profile local-llm up -d` and set
`LLM_PROVIDER=ollama` in `.env`.

Stop everything: `docker compose down -v`
