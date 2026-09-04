# SmartBank — Build Spec

Personal finance and banking assistant. ASD 2026, Canvas Group 12.

| | |
|---|---|
| Team leader | William Por |
| Repo | https://github.com/khoi2532005-ship-it/AvSoDe.git |
| Cloud | Azure |
| LLM(s) | Qwen, Llama (via Ollama locally) |
| Database | SQLite, one file per service |

## Team

| # | Name | Student ID | Feature |
|---|---|---|---|
| 1 | William Por | 25357118 | Accounts and Customers |
| 2 | David Lee | 24970903 | Loans and Credit |
| 3 | Duc Minh Khoi Tran | 25001975 | Fraud Alerts / Notifications |
| 4 | Cong Bao Nguyen | 14479051 | Budgeting and Spending Insights |
| 5 | Aidan Lei | 25469750 | Transactions |

---

## Architecture

Five independent microservices, one per student. Each owns its own frontend, backend API, and SQLite file. Services talk to each other over HTTP only — never by reading another service's database file directly.

```
                    index.html (shared home page)
                              |
   +---------+---------+------+------+---------+
   |         |         |             |         |
Accounts  Trans-    Fraud        Budgeting   Loans
(William) actions   Alerts       (Bao)       (David)
          (Aidan)   (Khoi)
   |         |         |             |         |
 accounts  trans    fraud        budgets    loans
  .db       .db      .db           .db        .db
                              |
                    Ollama (Qwen / Llama)
```

All services are brought up together by one shared `docker-compose.yml`. Ollama runs as a shared service that all five backends call.

### Suggested repo layout

```
/services
  /accounts        (William)
  /transactions    (Aidan)
  /fraud-alerts    (Khoi)
  /budgeting       (Bao)
  /loans           (David)
    /frontend
    /backend
    /db            (schema.sql + seed.sql)
    Dockerfile
/shared
  /css             (common theme)
  index.html       (links to all five frontends)
docker-compose.yml
```

### Suggested port allocation

Needs team sign-off, but something fixed is required before integration works.

| Service | Frontend | Backend |
|---|---|---|
| Accounts | 3001 | 8001 |
| Transactions | 3002 | 8002 |
| Fraud Alerts | 3003 | 8003 |
| Budgeting | 3004 | 8004 |
| Loans | 3005 | 8005 |
| Ollama | — | 11434 |

---

## Shared conventions

These need to be agreed as a team before anyone integrates. Getting these wrong is the most likely cause of a broken showcase.

**IDs.** `customer_id` is owned by Accounts and is the join key across every service. `account_id` is owned by Accounts. `transaction_id` is owned by Transactions. No service invents an ID that belongs to another service.

**Dates.** ISO 8601 strings in SQLite `TEXT` columns: `2026-08-23T14:30:00`. No local formats, no epoch ints.

**Money.** `REAL` is fine for a demo. Always send amounts as plain numbers, never pre-formatted strings with currency symbols.

**Categories.** One taxonomy, owned by Transactions. Every other service references category by name string from that list. See open issue #1.

**Error shape.** Same JSON body from every backend so frontends can handle failures uniformly:

```json
{ "error": "message here", "code": 404 }
```

**Seed data.** Every table needs 10+ records, and they have to be *consistent across services*. If Accounts seeds customers 1–10, then Transactions, Budgeting, Loans and Fraud Alerts all seed against those same customer IDs. Agree the seed customer set first, then everyone builds against it.

---

## Cross-service dependencies

```
Accounts (William)  <-- root, nothing depends on it upstream
   ^   ^   ^   ^
   |   |   |   |
   |   |   |   +---- Loans (customer profile)
   |   |   +-------- Budgeting (customer)
   |   +------------ Fraud Alerts (account context for AI explanation)
   +---------------- Transactions (account + customer)

Transactions (Aidan)
   ^   ^
   |   +------------ Budgeting (actual spending per category)
   +---------------- Fraud Alerts (transactions to scan)
```

**Build order:** Accounts → Transactions → everything else.
**Startup order in compose:** same. Add `depends_on` accordingly.

If Accounts or Transactions is down, three other features have nothing to show. Both should return sensible empty results rather than 500s, and dependent frontends should degrade gracefully rather than blanking out.

---

## Feature 1 — Accounts and Customers (William)

Manage customer profiles and their bank accounts, plus an AI-generated plain-English summary of a customer's accounts and a basic risk profile.

**Frontend**
- Customer dashboard showing customer details and linked accounts
- Create / view / edit / delete customer profile
- Create and link a bank account to a customer
- View account balance, type, status; edit type/status; close account
- Search and filter customers and accounts
- Button to request an AI account summary or customer risk profile

**Backend / API**
- Customer CRUD
- Account CRUD
- Link accounts to customers by customer ID
- Get single customer with accounts; list all customers/accounts
- Validation of customer and account data
- Account status management (active / inactive / closed)
- AI: send customer and account data to Ollama, return a plain-English summary
- AI: generate a basic risk profile from account data, return explanation to frontend
- Error handling and request validation

**Exposes to other services:** customer lookup by ID, account lookup by ID, accounts for a customer.

**Database — `accounts.db`**

```sql
CREATE TABLE customers (
  customer_id   INTEGER PRIMARY KEY,
  first_name    TEXT NOT NULL,
  last_name     TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  phone         TEXT,
  date_of_birth TEXT,
  address       TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT
);

CREATE TABLE accounts (
  account_id     INTEGER PRIMARY KEY,
  customer_id    INTEGER NOT NULL REFERENCES customers(customer_id),
  account_number TEXT NOT NULL UNIQUE,
  account_type   TEXT NOT NULL,        -- savings | checking | credit
  balance        REAL NOT NULL DEFAULT 0,
  currency       TEXT NOT NULL DEFAULT 'AUD',
  status         TEXT NOT NULL,        -- active | inactive | closed
  created_at     TEXT NOT NULL,
  updated_at     TEXT
);

CREATE TABLE ai_summaries (
  summary_id   INTEGER PRIMARY KEY,
  customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
  summary_type TEXT NOT NULL,          -- account_summary | risk_profile
  summary_text TEXT NOT NULL,
  risk_level   TEXT,                   -- low | medium | high
  created_at   TEXT NOT NULL
);
```

---

## Feature 2 — Loans and Credit (David)

Create, view, update and delete loan applications and repayment schedules, with AI explaining eligibility and approval decisions and suggesting repayment options.

**Frontend**
- Create and submit loan applications
- View application details and status; update or delete applications
- View repayment schedules and upcoming payments; update repayment info
- View loan eligibility and decision explanations
- AI: explain approval/rejection in plain language
- AI: compare repayment options and recommend one
- Search and filter applications and repayment records

**Backend / API**
- Submit application; retrieve application details and status
- Retrieve repayment schedules; update repayment information
- Retrieve loan eligibility information
- CRUD on loan applications and repayment schedules
- AI: explain eligibility, explain approval/rejection, explain repayment schedule, suggest repayment options

**Consumes:** Accounts (customer profile for eligibility).

**Database — `loans.db`**

```sql
CREATE TABLE loan_applications (
  loan_id          INTEGER PRIMARY KEY,
  customer_id      INTEGER NOT NULL,   -- logical FK -> Accounts service
  loan_type        TEXT NOT NULL,      -- personal | home | auto
  requested_amount REAL NOT NULL,
  loan_purpose     TEXT,
  application_date TEXT NOT NULL,
  status           TEXT NOT NULL,      -- pending | approved | rejected
  interest_rate    REAL,
  approved_amount  REAL
);

CREATE TABLE repayments (
  repayment_id    INTEGER PRIMARY KEY,
  loan_id         INTEGER NOT NULL REFERENCES loan_applications(loan_id),
  due_date        TEXT NOT NULL,
  payment_amount  REAL NOT NULL,
  principal_amount REAL,
  interest_amount  REAL,
  amount_paid     REAL DEFAULT 0,
  payment_date    TEXT,
  payment_status  TEXT NOT NULL        -- due | paid | overdue
);
```

---

## Feature 3 — Fraud Alerts / Notifications (Khoi)

Monitor account activity and raise alerts when transactions look suspicious.

**Design decisions**

- Detection is **deterministic and rule-based**, driven by configurable thresholds in `alert_rules`. The LLM is used only to explain an alert in plain English *after* a rule has fired. It never makes the detection decision.
- `alerts` **snapshots** the transaction fields (amount, recipient, datetime, category) at the moment the alert is created rather than re-fetching them live. Faster to query, and the dashboard still works during the demo if the Transactions service is down.
- `rule_id` is a real enforced foreign key inside this service's own SQLite file. `customer_id` and `transaction_id` are logical foreign keys — resolved by calling other students' APIs, not enforced by the database.
- Calling the Transactions API during a scan is what satisfies the proposal's cross-feature integration requirement.

**Frontend**

*Alert dashboard*
- View alert details
- Filter alerts by status, date, amount
- Sort alerts by status, amount, date
- Open an alert to view full details and AI explanation
- Update alert status; delete alert

*Alert rules management*
- View all configured rules
- Create, update, delete rules
- Enable / disable rules

*Detection*
- Run detection across transactions to evaluate them

*AI*
- Request an explanation of why a transaction was flagged

**Backend / API**

*CRUD*
- Create: alert record, alert rule
- Read: all alerts, filter by status/amount/detail; alert rules
- Update: alert status (reviewed / dismissed / confirmed); alert rule (threshold, name, enabled state)
- Delete: alert, alert rule

*API*
- Expose alert and rule data to other features via this service's own API
- Call the Transactions API to retrieve transaction data for scanning
- Call the Accounts API for account context to support AI explanation

*Other*
- Evaluate transactions against enabled rules
- Generate an alert record for any transaction that breaches a rule
- Build a prompt from the flagged transaction + triggered rule + account context
- Send the prompt to the LLM and store the returned English explanation

**Rule types to implement** (thresholds live in the DB, not in code)

| Rule type | Threshold meaning |
|---|---|
| `amount_over` | Single transaction above X |
| `velocity` | More than N transactions within M minutes |
| `unusual_time` | Transaction between hour X and hour Y |
| `new_recipient_high_value` | First transfer to a recipient above X |

**Consumes:** Transactions (transaction data to scan), Accounts (account context for prompts).

**Database — `fraud.db`**

```sql
CREATE TABLE alert_rules (
  rule_id         INTEGER PRIMARY KEY,
  rule_name       TEXT NOT NULL,
  rule_type       TEXT NOT NULL,
  threshold_value REAL NOT NULL,
  severity        TEXT NOT NULL,       -- low | medium | high
  enabled         INTEGER NOT NULL DEFAULT 1,
  created_at      TEXT NOT NULL
);

CREATE TABLE alerts (
  alert_id               INTEGER PRIMARY KEY,
  rule_id                INTEGER NOT NULL REFERENCES alert_rules(rule_id),
  customer_id            INTEGER NOT NULL,   -- logical FK -> Accounts
  transaction_id         INTEGER NOT NULL,   -- logical FK -> Transactions
  transaction_amount     REAL NOT NULL,      -- snapshot
  transaction_recipient  TEXT,               -- snapshot
  transaction_datetime   TEXT,               -- snapshot
  transaction_category   TEXT,               -- snapshot
  severity               TEXT NOT NULL,
  status                 TEXT NOT NULL,      -- new | reviewed | dismissed | confirmed
  ai_explanation         TEXT,
  explanation_generated_at TEXT,
  created_at             TEXT NOT NULL
);
```

---

## Feature 4 — Budgeting and Spending Insights (Bao)

Create and manage monthly budgets per spending category, track actual spending against each budget, and get AI-generated personalised insights on where the customer is over or under budget.

**Frontend**
- View all budgets for the month with progress bars
- Create a new budget; edit an existing budget's limit or category; delete a budget
- AI insight panel: request and display personalised spending advice
- Highlight over-budget categories with alerts

**Backend / API**
- Create and manage budgets
- Retrieve budget details and spending summaries
- Retrieve actual spending data from the Transactions API
- Calculate spent vs limit per category
- Retrieve AI insight history
- CRUD on budgets and budget categories
- AI: generate personalised spending insights, explain why a category is over/under, compare actual vs limit and identify trends, suggest budget limit adjustments

**Consumes:** Transactions (spending per category), Accounts (customer).

**Database — `budgets.db`**

```sql
CREATE TABLE budgets (
  budget_id     INTEGER PRIMARY KEY,
  customer_id   INTEGER NOT NULL,      -- logical FK -> Accounts
  category      TEXT NOT NULL,         -- from shared taxonomy
  monthly_limit REAL NOT NULL,
  month         INTEGER NOT NULL,      -- 1-12
  year          INTEGER NOT NULL,
  created_at    TEXT NOT NULL
);

CREATE TABLE budget_insights (
  insight_id   INTEGER PRIMARY KEY,
  budget_id    INTEGER NOT NULL REFERENCES budgets(budget_id),
  insight_text TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  model_used   TEXT
);

CREATE TABLE categories (
  category_id   INTEGER PRIMARY KEY,
  category_name TEXT NOT NULL UNIQUE,
  description   TEXT
);
```

> `categories` here duplicates Aidan's `transaction_categories`. See open issue #1 — one of these should go, or become a read-only mirror.

---

## Feature 5 — Transactions (Aidan)

Create, record and view all financial transactions (deposits, withdrawals, transfers). Auto-categorises transactions using AI and exposes transaction data by API to the other features — this service is the backbone for Fraud Alerts and Budgeting.

**Frontend**
- Transaction history as a table or timeline
- Create a transaction (deposit / withdrawal / transfer)
- View transaction detail (amount, date, category, counterparty, notes)
- Edit notes and category override; delete transaction
- Search and filter by date range, amount, category, type, counterparty
- Sort by date, amount, category
- View AI-generated category per transaction
- View transactions flagged as unusual, and request an AI explanation
- Export transaction history as CSV
- View spending trends by category over time

**Backend / API**
- Create transaction; retrieve all transactions for a customer; retrieve one transaction
- Retrieve transactions filtered by date, amount, category, type
- **Dedicated endpoints exposing transaction data to Fraud Alerts and Budgeting**
- Update transaction details (notes, category); delete transaction
- Retrieve spending summary by category for a period
- AI: auto-categorise transactions from merchant name, description and amount
- AI: analyse patterns and flag unusual spending
- AI: explain in plain English why a transaction was flagged
- AI: detect duplicates and fraudulent patterns

**Exposes to other services:** transactions for a customer (with date/amount filters), spending summary by category, the category taxonomy.

**Database — `transactions.db`**

```sql
CREATE TABLE transactions (
  transaction_id      INTEGER PRIMARY KEY,
  customer_id         INTEGER NOT NULL,  -- logical FK -> Accounts
  account_id          INTEGER NOT NULL,  -- logical FK -> Accounts
  transaction_type    TEXT NOT NULL,     -- deposit | withdrawal | transfer
  sender_name         TEXT,
  sender_account_id   TEXT,
  sender_bank_code    TEXT,
  recipient_name      TEXT,
  recipient_account_id TEXT,
  recipient_bank_code TEXT,
  amount              REAL NOT NULL,
  datetime_sent       TEXT NOT NULL,
  datetime_processed  TEXT,
  process_state       TEXT NOT NULL,     -- pending | completed | failed
  notes               TEXT,
  generated_category  TEXT,
  flagged_unusual     INTEGER DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT
);

CREATE TABLE transaction_categories (
  category_id   INTEGER PRIMARY KEY,
  category_name TEXT NOT NULL UNIQUE,
  description   TEXT,
  keywords      TEXT,                    -- merchant names/descriptions
  is_default    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE spending_patterns (
  pattern_id             INTEGER PRIMARY KEY,
  customer_id            INTEGER NOT NULL,
  category               TEXT NOT NULL,
  average_amount         REAL,
  frequency              REAL,           -- transactions per month
  typical_datetime_range TEXT,
  last_updated           TEXT NOT NULL
);
```

**Proposed category list** (needs team agreement, then seed into `transaction_categories`):

`groceries`, `rent`, `utilities`, `entertainment`, `transportation`, `healthcare`, `dining`, `shopping`, `income`, `transfer`, `other`

---

## Agentic AI workflow — Plan → Act → Observe → Adapt

Every student must demonstrate this loop. No feature section in the registration form currently describes it, so each person needs to map their feature onto the four stages. Template:

| Stage | What it means |
|---|---|
| **Plan** | Decide what needs doing and what data is required |
| **Act** | Call the API / DB / LLM to do it |
| **Observe** | Check the result — did it succeed, is the output usable? |
| **Adapt** | Retry, fall back, refine the prompt, or change approach based on what was observed |

**Worked example — Fraud Alerts:**

1. **Plan** — pick which enabled rules apply and which transaction window to scan.
2. **Act** — call the Transactions API, evaluate each transaction against the rules, create alert records for breaches, build a prompt and send it to Ollama.
3. **Observe** — check the LLM actually returned a usable explanation, that it references the right rule and amount, and that it isn't empty or truncated.
4. **Adapt** — if the explanation is unusable, retry with a tightened prompt; if Transactions is unreachable, fall back to the last scanned window and surface a clear message instead of failing silently.

Each of the other four features needs its own version of this written down before the showcase.

---

## Deliverables checklist

### Per student

- [ ] One frontend microservice
- [ ] One backend/API microservice
- [ ] One database microservice
- [ ] CRUD working end to end through frontend and backend
- [ ] **10+ records seeded in every table** you own
- [ ] Frontend integrated with backend API, calling the Agentic AI model
- [ ] Microservices integrated into the shared GitHub project
- [ ] Own CI/CD workflow implemented and maintained
- [ ] Visible GitHub commit history and passing GitHub Actions runs
- [ ] Plan → Act → Observe → Adapt loop demonstrated
- [ ] Pre-testing and post-testing evidence kept

### Team

- [ ] One integrated Agentic AI application
- [ ] All 15 microservices integrated into one working app
- [ ] Every frontend and backend demonstrates successful LLM interaction at each showcase
- [ ] Shared GitHub repo with a common project structure
- [ ] Shared `docker-compose.yml` running all services plus shared AI services
- [ ] Unified `index.html` linking every feature
- [ ] Consistent CSS theme across the whole app
- [ ] All services integrated and tested before each release
- [ ] Integration issues resolved before each showcase
- [ ] Documentation maintained across all releases
- [ ] Demo runs from a single team member's machine
- [ ] Every member demos their own feature inside the integrated app
- [ ] One technical report (PDF) per release, submitted on Canvas

---

## Open issues

Things that will break integration if they aren't resolved. Roughly in priority order.

**1. Two competing category taxonomies.**
Aidan has `transaction_categories`, Bao has `categories`. Khoi's alerts and Bao's budgets both store category as a free-text string. If the strings don't match exactly, budget totals and alert filters silently break. *Fix: Aidan owns the taxonomy and exposes it by API; everyone else references it by name. Bao's table becomes a mirror or is dropped.*

**2. Fraud detection scope overlaps between two features.**
Aidan's Transactions feature lists "flag unusual spending", "detect fraudulent patterns" and "explain why a transaction was flagged as unusual" — which is Khoi's entire feature. Two services writing fraud logic is duplicated work and a confusing demo. *Fix: agree a split. Suggested — Transactions owns AI categorisation and the `flagged_unusual` boolean as a lightweight hint; Fraud Alerts owns rule evaluation, alert records, alert lifecycle and the fraud explanations.*

**3. LLM nomination vs tutor condition.**
The form now lists Qwen and Llama, but the tutor's approval was conditional with the comment "no models are nominated". Confirm with the tutor that this is now satisfied. Also settle the specific model tags everyone runs (e.g. `llama3.2`, `qwen2.5`) so results are consistent across machines.

**4. Ollama local vs Azure cloud.**
The form nominates Azure, but the working setup is Ollama running locally. Clarify whether Azure is a deployment target for a later release or something needed now.

**5. Nobody owns authentication.**
David and Bao both list "Authenticate and manage user access" in their backend functions. Either William's Accounts service owns it for everyone, or it's cut from scope for the demo. Two half-implementations is the worst outcome.

**6. Seed data consistency.**
Ten records per table is required individually, but the records have to line up across services. Agree the seed customer set (IDs and names) first, then everyone seeds against it. Otherwise Khoi has alerts for customers who don't exist in Accounts.

**7. Fraud alerts store `customer_id` but not `account_id`.**
Fine if all rules are customer-level. If any rule ends up being per-account, `account_id` will need adding to `alerts`. Worth deciding now rather than migrating later.
