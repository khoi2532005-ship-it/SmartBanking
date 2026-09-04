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
