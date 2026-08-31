Student 1 Name 

William Por 

Feature Name 

Accounts and Customers 

Feature Purpose 

Manage customer profiles and their bank accounts. The feature will allow users to create, view, update, and delete customer information and bank accounts. It will also provide an AI-generated plain-English summary of a customer’s accounts and financial information, including a basic customer risk profile based on available account data. 

Frontend Functions 

Customer dashboard showing customer details and account information 

Create new customer profile 

View customer profile and account details 

Edit/update customer information 

- Delete customer profile 

Create and link a bank account to a customer 

View account balance, account type and status 

Edit account details such as account type/status 

Delete/close an account 

Search and filter customers/accounts 

Button/function to request an AI-generated account summary or customer risk profile 

 

Backend/API Functions 

Customer CRUD: Create, read, update and delete customer profiles 

Account CRUD: Create, read, update and delete bank accounts 

Link accounts to customers using customer IDs 

API endpoints for retrieving individual customers and their accounts 

API endpoint for listing all customers/accounts 

Validation of customer and account data 

Account status management (active, inactive, closed) 

SQLite database operations using the backend API 

AI function: Send customer/account data to Ollama using Llama/Qwen and generate a plain-English account summary 

AI function: Generate a basic customer risk profile based on relevant account information, with the AI explanation returned to the frontend 

Error handling and validation for API requests 

Database Tables 

Customers: customer_id, first_name, last_name, email, phone, date_of_birth, address, created_at, updated_at 

Accounts: account_id, customer_id, account_number, account_type, balance, currency, status, created_at, updated_at 

AI_Summaries: summary_id, customer_id, summary_type, summary_text, risk_level, created_at 

 

Student 2 Name 

David Lee 

Feature Name 

Loans and Credit 

Feature Purpose 

This feature will allow users to create, view, update, and delete loan applications and repayment schedules. It also uses an AI to explain why loan eligibility or approval decisions were made and make suggestions. 

Frontend Functions 

Create and submit loan applications  

View loan application details and status  

Update or delete loan applications  

View repayment schedules and upcoming payments  

Update repayment information  

View loan eligibility and decision explanations  

Use AI to explain approval/rejection reasons in plain language  

Use AI to compare repayment options  

Receive recommendations for suitable repayment options  

Search and filter loan applications and repayment records 

 

Backend/API Functions 

API Functions 

Submit loan application  

Retrieve loan application details and status  

Retrieve repayment schedules  

Update repayment information  

Retrieve loan eligibility information  

Authenticate and manage user access  

CRUD Functions 

Create: Create loan applications and repayment schedules  

Read: View, search, and filter loan applications and repayment records  

Update: Modify loan application details and repayment schedules  

Delete: Cancel/delete loan applications or repayment records where permitted  

AI Functions 

Explain loan eligibility in plain language  

Explain the reasons behind loan approval or rejection  

Explain repayment schedules and payment requirements  

Suggest suitable repayment options  

 

Database Tables 

LoanApplications 

Loan ID  

Customer ID  

Loan type  

Requested amount  

Loan purpose  

Application date  

Status  

Interest rate  

Approved amount 

 

 

Repayments 

Repayment ID  

Loan ID  

Due date  

Payment amount  

Principal amount  

Interest amount  

Amount paid  

Payment date  

Payment status 

 

 

 

 

Student 3 Name 

Duc Minh Khoi Tran 

Feature Name 

Fraud Alerts/ Notification 

Feature Purpose 

This feature monitor account activity and raise alerts when transactions look suspicious. 

Frontend Functions 

Alert Dashboard 

View alerts details 

Filter alerts by status, date, amount 

Sort alert by status, amount, date 

Open an alert to view full details and AI explanation 

Update alert status 

Delete alert 

Alert Rules Management 

View all configured rules 

Create, delete, update rules 

Enable, disable rules 

Detection 

Run detection across transactions to evaluate them 

AI Mode 

Request explanation why a transaction is flagged 

 

Backend/API Functions 

CRUD function: 

Create: Alerts record, alert rule 

Read: All alerts, filter by status, amount and detail; Alert Rules 

Update: Alert’s status (reviewed, dismissed or confirmed), Alert rules (threshold, name or enable state) 

Delete: Alert and alert rule 

API functions: 

Expose alert and rule data to other features via this feature’s own API 

Use Transactions feature API to retrieve transaction data for scanning 

Use account context from accounts feature to support AI explanation 

Other functions: 

Evaluate transactions against enabled rules 

Generate alert record for transactions that breaches a rule 

Build a prompt from flagged transaction, the triggered alert rule and account context. 

Send prompt to LLM to return an English explanation 

Database Tables 

AlertRules 

Rule ID 

Rule name 

Rule type 

Threshold values 

Severity 

Enabled 

Created date 

Alerts 

Alert ID 

Rule ID 

Customer ID 

Transaction ID 

Transaction amount 

Transaction recipient 

Transaction datetime 

Transaction category 

Severity 

Status 

AI Explanation 

Explanation generated date 

Created date 

 

 

Student 4 Name 

Cong Bao Nguyen 

Feature Name 

Budgeting and Spending Insights 

Feature Purpose 

Allows customers to create and manage monthly budgets per spending category, track actual spending against each budget, and receive AI-generated personised insights explaining where they are over or under budget and what to adjust. 

Frontend Functions 

View all budgets for the month with progress bars 

Create a new budget 

Edit an existing budget’s limit or category 

Delete a budget 

View AI Insight panel: request and display a personalised spending advice message 

Highlight over-budget categories with alerts 

Backend/API Functions 

API Function 

Create and manage budgets 

Retrieve budget details and spending summaries 

Retrieve actual spending data from the Transactions API 

Calculate spent versus limit per category 

Retrieve AI-generated insight history 

Authenticate and manage user access 

CRUD Functions 

Create: Create budgets and budget categories 

Read: View, search, and filter budgets and spending summaries 

Update: Modify budget limits, categories, and budget periods 

Delete: Remove budget categories where permitted 

AI functions 

Generate personalised spending insights in plain language 

Explain why a category is over or under budget 

Compare actual spending against budget limits and identify trends 

Suggest suitable budget limit adjustments 

Database Tables 

Budgets 

Budget ID 

Customer ID 

Category 

Monthly limit 

Month 

Year 

Created date 

Budget Insights 

Insight ID 

Budget ID 

Insight text 

Generated date 

Model used 

Categories 

Category ID 

Category name 

Description 

 

Student 5 Name 

Aidan Lei 

Feature Name 

Transactions 

Feature Purpose 

Enable users to create, record, and view all financial transactions (deposits, withdrawals, and transfers) within their bank accounts. The feature will automatically categorize transactions using AI and flag unusual spending patterns or anomalies to help users monitor their financial activity. Transaction data will be exposed via API to support other features, particularly the Fraud Alerts feature for cross-feature transaction analysis. 

Frontend Functions 

View transaction history/list with customer transactions displayed in a table or timeline format 

Create new transaction (deposit, withdrawal, or transfer) 

View detailed transaction information (amount, date, category, recipient/sender, notes) 

Edit transaction details (notes, category override) 

Delete transaction record 

Search and filter transactions by date range, amount, category, transaction type, recipient/sender 

Sort transactions by date, amount, category 

View AI-generated transaction category for each transaction 

View transactions flagged as unusual or suspicious 

Request AI explanation for why a transaction was flagged as unusual 

Export transaction history as CSV or report 

View spending trends by category over time 

