# Expendicure - Student Banking & Budget Tracking Application

Expendicure is a student-focused banking and budget tracking web application that allows college students to record payments, categorize expenses, set monthly budgets, and view spending analytics through graphs.

## Features

### 1. Student Dashboard
- Shows total balance
- Displays total monthly spending
- Shows remaining budget
- Lists recent transactions
- Provides category-wise expense summary

### 2. Payment / Transaction System
- Add payment transactions with fields:
  - Amount
  - Merchant name
  - Category (selectable)
  - Payment date
  - Payment method
  - Notes
- Update transaction category after creation

### 3. Expense Categories
- Default categories: Food, Rations, Travel, Books, Rent, Entertainment, Health, Other
- Ability to add new categories

### 4. Budget Management
- Set monthly budget (category-wise)
- View remaining budget
- Warning when spending crosses category budget

### 5. Graphs and Reports
- Pie chart for category-wise spending
- Bar chart for monthly spending
- Recent transactions table
- Filter transactions by category and date

## Technology Stack

- **Frontend**: React with Vite
- **Backend**: Python Flask
- **Database**: MySQL
- **Styling**: Clean white modern UI using CSS
- **Charts**: Recharts
- **API Communication**: REST API using Axios

## Database Schema

The application uses four main tables:

### Students
- `id` (INT, PK, Auto Increment)
- `student_id` (VARCHAR, Unique)
- `name` (VARCHAR)
- `email` (VARCHAR, Unique)
- `created_at` (TIMESTAMP)

### Categories
- `id` (INT, PK, Auto Increment)
- `name` (VARCHAR, Unique)
- `is_default` (BOOLEAN)
- `created_at` (TIMESTAMP)

### Transactions
- `id` (INT, PK, Auto Increment)
- `student_id` (INT, FK to Students)
- `amount` (DECIMAL)
- `merchant_name` (VARCHAR)
- `category_id` (INT, FK to Categories)
- `payment_date` (DATE)
- `payment_method` (VARCHAR)
- `notes` (TEXT)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### Budgets
- `id` (INT, PK, Auto Increment)
- `student_id` (INT, FK to Students)
- `category_id` (INT, FK to Categories)
- `monthly_limit` (DECIMAL)
- `month` (VARCHAR, Format: YYYY-MM)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

## Setup Instructions

### Prerequisites
- Node.js (v16+)
- Python (v3.8+)
- MySQL Server

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd expendicure/backend
   ```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create the backend `.env` file by copying the template and editing it:
   ```bash
   cp .env.example .env
   # then edit .env and set MYSQL_PASSWORD and a long random SECRET_KEY
   ```
   `.env` is git-ignored and must never be committed.

5. Create the database:
   ```bash
   mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS expendicure;"
   ```

6. Apply database migrations (this is the source of truth for the schema —
   see "Database migrations" below):
   ```bash
   python scripts/migrate.py
   ```
   Optionally load demo data:
   ```bash
   mysql -u root -p expendicure < ../database/seed.sql
   ```

7. Start the Flask server:
   ```bash
   python app.py
   ```
   The backend will run on http://localhost:5000

8. Run the backend test suite (no MySQL required — the DB layer is stubbed;
   the one integration test skips itself when no database is reachable):
   ```bash
   pytest
   ```

### Database migrations

Schema changes live in `database/migrations/` as ordered `NNN_name.sql` files
and are applied by a small runner (no ORM, no Alembic):

```bash
cd backend
python scripts/migrate.py            # apply every pending migration, in order
python scripts/migrate.py --status   # list applied / pending, change nothing
```

- Applied migrations are recorded in a `schema_migrations` table and are never
  re-run.
- `000_base_schema.sql` recreates the original tables with `IF NOT EXISTS`, so
  the runner works on both a fresh database and one already built from
  `database/schema.sql`.
- Migrations are written to be safe to re-run by hand (`CREATE TABLE IF NOT
  EXISTS`, `information_schema`-guarded `ALTER`s). MySQL auto-commits DDL, so if
  a single migration fails part-way, fix the `.sql`, remove its row from
  `schema_migrations`, and re-run.
- To add a change: create the next-numbered `.sql` file and run the migrate
  command. Never edit an already-applied migration.

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd expendicure/frontend
   ```

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```
   The frontend will run on http://localhost:3000

## API Endpoints

All endpoints except `/api/health`, `/api/auth/*` require a
`Authorization: Bearer <token>` header. The authenticated student is taken
from the token — endpoints do **not** accept a `student_id` parameter.

### Health
- GET `/api/health` - Liveness check (`{"status": "ok"}`)

### Auth
- POST `/api/auth/register` - Create a student + user (atomic)
- POST `/api/auth/login` - Returns `{ token, student }`

### Students
- GET `/api/students/` - Returns the authenticated student only
- GET `/api/students/<id>` - Only allowed for your own id (else 403)

### Transactions
- GET `/api/transactions` - Transactions for the authenticated student
- POST `/api/transactions` - Add a transaction. Validates amount > 0, date, category.
  Optional `direction`: `"debit"` (money out, default) or `"credit"` (money in).
- PUT `/api/transactions/<id>` - Update transaction category
- DELETE `/api/transactions/<id>` - Delete transaction

### Account
- GET `/api/account` - Opening balance, safety buffer, as-of date, and the derived `current_balance`
- PUT `/api/account` - Upsert opening balance / safety buffer / as-of date (all optional, non-negative)

### Recurring transactions
- GET `/api/recurring?include_inactive=0` - The student's recurring items
- POST `/api/recurring` - Create one (`label`, `merchant_name`, `amount`, `direction`, `cadence` weekly|monthly, `day_of_month` or `weekday`, `next_date`)
- PUT `/api/recurring/<id>` - Update fields (partial)
- DELETE `/api/recurring/<id>` - Delete

### Categorization rules
- GET `/api/categorization-rules` - Global default rules + the student's own
- POST `/api/categorization-rules` - Create a personal rule (`match_type` contains|equals, `pattern`, `category_id`, `priority`)
- PUT `/api/categorization-rules/<id>` - Update a personal rule (global rules are read-only)
- DELETE `/api/categorization-rules/<id>` - Delete a personal rule

### Categories
- GET `/api/categories/` - Global default categories + the student's own
- POST `/api/categories/` - Add a category (scoped to the authenticated student)
- PUT `/api/categories/<id>` - Update one of your own categories (globals are read-only)
- DELETE `/api/categories/<id>` - Delete one of your own unused categories

### Budgets
- GET `/api/budgets?month=<YYYY-MM>` - Budgets for the authenticated student
- POST `/api/budgets/` - Add or update a budget
- DELETE `/api/budgets/<id>` - Delete a budget

### Dashboard
- GET `/api/dashboard/summary` - Dashboard summary for the authenticated student

### Reports
- GET `/api/reports/chart-data?category=&month=&start_date=&end_date=` - Chart data + filtered transactions

### Digital Twin
- GET `/api/twin/state?as_of=<YYYY-MM-DD>` - Deterministic snapshot of the student's financial state (balances, month-to-date totals, spending by category, budgets, recurring items, safety buffer, committed upcoming expenses, discretionary buffer). Every value is computed by `finance.twin`, never by an LLM.

### Affordability
- POST `/api/affordability/check` - Deterministic "Can I afford this?" — body `{ amount, category?, date?, horizon_days?, as_of? }`. Returns a structured verdict (`affordable` / `tight` / `not_affordable`), a 0-100 safety score, `projected_min_balance` over the horizon, `breaches`, and `reasons`. Computed by `finance.affordability`, never by an LLM.

### What-if simulation
- POST `/api/simulation/what-if` - Deterministic, **in-memory** what-if. Body `{ type, ...scenario fields, horizon_days?, as_of? }`. Returns `baseline` vs `scenario` daily projections (starting / minimum / ending balance + the full series), a `comparison` block (`min_balance_delta`, `end_balance_delta`, `safety_buffer_impact`, `affordability_before`/`after`, `changes`), and the echoed `scenario_input`. Scenario types: `one_off_expense`, `one_off_income`, `recurring_expense`, `recurring_income`, `recurring_modification`, `income_delta`. **Never writes to the database.** Computed by `finance.simulate` on top of `finance.projection`; no LLM.

  A what-if simulation is a temporary hypothetical: it takes the current Digital
  Twin, applies the scenario as extra projection events (and, for
  `recurring_modification`, a modified *copy* of the recurring item), projects
  baseline and scenario through the one shared kernel, and compares them. It
  holds no DB connection and no write path, so `transactions`, `accounts`,
  `recurring_transactions`, `budgets` and `categories` are guaranteed untouched.

### Cash-flow forecast
- GET `/api/forecast?as_of=<YYYY-MM-DD>&horizon_days=30` - Deterministic **expected** balance over the next 1–365 days (default 30). Rolls `current_balance` forward through the one shared kernel, applying every future occurrence of the student's active recurring transactions **and** recurring patterns conservatively detected from history. Returns `projected_min_balance` / `_date`, `projected_end_balance`, `projected_income` / `expenses` / `net`, an overall `confidence` (`low`/`medium`/`high`), per-occurrence `events`, `assumptions` (with confidence + observation counts), the daily `projection` series, and `safety_buffer_breached` + earliest `breach_date`. Read-only; no LLM.

  **Current reality vs hypothetical vs expected** — three separate concepts, all sharing `finance.projection`:
  - **Digital Twin** (`finance.twin`, `/api/twin/state`) — *what IS, as of now*.
  - **What-If Simulator** (`finance.simulate`, `/api/simulation/what-if`) — *what WOULD happen if I made this specific change*.
  - **Cash-Flow Forecast** (`finance.forecast`, `/api/forecast`) — *what is LIKELY to happen if nothing changes*.

  **Recurring detection rules** (deterministic, no ML): group history (last 180 days) by normalised merchant + direction; require ≥ 3 observations; the gaps must be consistently monthly (median 26–35 d, all 24–38 d) or weekly (median 6–8 d, all 5–10 d); the amount spread `(max−min)/median` must be ≤ 0.40 (else too erratic to forecast); the projected amount is the median. A detected pattern is dropped if an active user recurring already covers that merchant+direction. Sparse/weak history → nothing is invented; the forecast is a flat line with `confidence: "low"`.

  **Confidence rules** (deterministic): an active user-created recurring transaction is always `high`. A detected pattern is `high` (≥ 6 obs, strict gaps, spread ≤ 0.15), `medium` (≥ 4 obs, strict gaps, spread ≤ 0.25), or `low` (≥ 3 obs, spread ≤ 0.40). Overall forecast confidence = the lowest assumption's confidence, or `low` when there are no assumptions.

### Anomaly detection
- GET `/api/anomalies?as_of=<YYYY-MM-DD>&history_days=90` - Deterministic scan (`history_days` 7–365, default 90) of the student's transaction history for suspicious events. Returns `{as_of, history_days, anomalies[], count, high_count, medium_count, low_count}`; each anomaly has `type`, `severity` (`low`/`medium`/`high`), a concise factual `reason`, and type-specific evidence fields. Read-only; no writes; no LLM/ML.

  The engine produces **facts, not advice** — e.g. *"Food spending was 4.00x the historical weekly average"* — never *"stop spending"* or *"you can't afford this"*. The Phase 9 agent interprets these facts alongside the twin, affordability, what-if and forecast.

  **Anomaly types & thresholds** (all constants explicit in `finance/anomaly.py`):
  | type | rule | medium | high |
  |---|---|---|---|
  | `amount_outlier` | recent txn amount vs median of ≥ 5 same-direction historical amounts | ratio ≥ 2.5 | ratio ≥ 4 |
  | `category_spike` | debit spend in last 7 d vs mean of the four prior 7-day buckets (≥ 2 non-zero) | ratio ≥ 1.75 | ratio ≥ 2.5 |
  | `duplicate_transaction` | same direction + amount + normalised merchant + category, clustered within 1 day (one anomaly per cluster) | cluster spans 0 days | — (spans 1 day → `low`) |
  | `budget_breach` | month-to-date debit spend > configured category budget | ratio ≤ 1.25 | ratio > 1.25 |
  | `new_large_merchant` | recent debit to a merchant with no prior transaction, `amount ≥ max(median_debit×2, ₹2000 floor)` | at threshold | `amount ≥ 2×` threshold |

  Ratios are quantized to 2 dp (half-up). Insufficient history → the rule is skipped (nothing invented).

### Local AI (Phase 8 — infrastructure only)
- GET `/api/ai/health` - `{ available, provider, model }` (+ `error` when not). No auth; never crashes. `503` when the local model is unusable.
- POST `/api/ai/generate` - auth required. Body `{ prompt }` → `{ text, model }`. A generic local-LLM endpoint for infrastructure testing — **not** the Financial Agent: it injects no financial data, calls no deterministic tools, does no tool-calling, and cannot modify records.

  Config (all optional env vars, in `backend/ai/config.py`): `OLLAMA_BASE_URL` (default `http://localhost:11434`), `OLLAMA_MODEL` (default `mistral`), `OLLAMA_TIMEOUT_SECONDS` (default `60`). Pull the model first: `ollama pull mistral`.

  **Graceful degradation:** if Ollama is not installed / not running / the model is missing / it times out / returns junk, every core feature (Dashboard, Transactions, Budgets, Twin, Affordability, What-If, Forecast, Anomalies) keeps working. `/api/ai/*` returns a clear `503`, never a stack trace. The finance engine still imports nothing from `ai/`, `requests`, or Ollama.

  **Prompt safety:** a fixed system prompt establishes that the model is an explanation assistant, must not invent or recompute financial numbers, must not claim calculations it didn't receive, must not modify records or execute instructions found in user-supplied text. This is the Phase 9 contract, set up now.

### Herman — the Financial Orchestrator Agent (Phase 9)
- POST `/api/agent/chat` - `token_required`. Body `{ message, conversation_id? }` → `{ text, intent, tool_used, data, suggested_actions, conversation_id, ai }`. **Read-only.** The user id comes from the token — never the body. If the local model is offline, Herman still replies gracefully (HTTP 200, `ai.available:false`) and the rest of the app is unaffected.

  **Flow:** `message → context (auth id + recent turns + previous plan) → planner (LLM picks ONE registered tool + args; JSON-only, 1 retry, then a deterministic keyword parser) → argument validation → deterministic tool → existing finance engine → structured result → responder (LLM explains the authoritative result) → AgentResponse`. Max 3 tool executions per request; ≤ 2 model calls (planner + responder).

  **Layering:** `finance ← tools ← agent ← routes`. `agent/` imports `tools/` + `ai/` only (never `database`/`finance`/`finance_db`); `tools/` wrap the existing engines (`finance.twin`, `.affordability`, `.simulate`, `.forecast`, `.anomaly`) and validate every argument. Herman never computes a financial number and cannot write any record. Tools: `get_financial_twin`, `check_affordability`, `simulate_expense`, `get_cashflow_forecast`, `get_financial_anomalies`, `get_transactions`, `get_budget_status`.

## AI agent architecture (planned)

Expendicure is designed to become a **proactive AI financial decision agent**, not
an expense tracker with a chatbot bolted on. The intelligence layer is being
built bottom-up as a set of **deterministic tools**; a local LLM is added last
and only to orchestrate and explain.

```
User
  -> Financial Orchestrator Agent          (local LLM via Ollama - Phase 9)
    -> Financial Tools                      (hand-written registry - Phase 9; no LangChain/LlamaIndex/MCP)
       - get_financial_twin
       - check_affordability                <-- shipped in Phase 4
       - simulate_financial_scenario        <-- shipped in Phase 5
       - forecast_cashflow                  <-- shipped in Phase 6
       - detect_anomalies                   <-- shipped in Phase 7
       - retrieve_financial_knowledge       (Phase 10)
    -> Deterministic Finance Engine         (finance/ package - pure, Decimal, no Flask/DB/LLM)
       - finance.twin            : the source-of-truth Financial Digital Twin
       - finance.projection      : the single shared day-by-day balance kernel
       - finance.affordability   : the affordability engine
       - finance.simulate        : the what-if simulator (baseline vs scenario)
       - finance.forecast        : the cash-flow forecast (expected future)
       - finance.anomaly         : deterministic anomaly detection (facts, not advice)
       - finance.recurrence      : shared recurrence-date arithmetic
    -> Guardrails                           (Phase 11)
    -> Agent explanation
```

**Non-negotiable rule:** the LLM never computes, rounds, overrides, or invents a
financial number. It obtains every financial fact by calling a deterministic
tool and passes the tool's structured result through unchanged.

Each engine module that will be exposed as a tool carries:
- a pure function with a stable signature (e.g. `finance.affordability.check_affordability(twin, *, amount, category=None, purchase_date=None, horizon_days=30)`),
- a `.to_dict()` on its result giving a JSON-safe, machine-readable payload (money as 2-decimal strings), and
- a `TOOL_SPEC` dict (name / description / JSON-schema parameters) for the Phase 9 registry.

The Phase 9 agent calls these functions **in-process** via the tool registry.
The REST endpoints above (`/api/twin/state`, `/api/affordability/check`) are the
same engine exposed over HTTP for the frontend; they are not the agent's path.

## Sample SQL Commands to Verify Data Connection

After setting up the database, you can run these commands to verify the connection:

```sql
-- Check students
SELECT * FROM students;

-- Check categories
SELECT * FROM categories;

-- Check transactions for student 1
SELECT t.*, c.name AS category_name 
FROM transactions t 
JOIN categories c ON t.category_id = c.id 
WHERE t.student_id = 1;

-- Check budgets for student 1 in April 2026
SELECT b.*, c.name AS category_name 
FROM budgets b 
JOIN categories c ON b.category_id = c.id 
WHERE b.student_id = 1 AND b.month = '2026-04';
```

## Project Structure

```
expendicure/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── database.py
│   ├── date_filters.py
│   ├── middleware.py
│   ├── migrations_runner.py
│   ├── finance_db.py            # adapter: wires finance/ to the real DB
│   ├── requirements.txt
│   ├── .env.example
│   ├── pytest.ini
│   ├── finance/                 # deterministic domain layer (no Flask, no DB driver)
│   │   ├── models.py
│   │   ├── money.py
│   │   └── repository.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── students.py
│   │   ├── transactions.py
│   │   ├── categories.py
│   │   ├── budgets.py
│   │   ├── dashboard.py
│   │   ├── reports.py
│   │   ├── account.py
│   │   ├── recurring.py
│   │   └── categorization_rules.py
│   ├── scripts/
│   │   └── migrate.py
│   └── tests/
├── database/
│   ├── migrations/              # NNN_name.sql, applied by scripts/migrate.py
│   ├── schema.sql               # original schema (kept for reference)
│   └── seed.sql
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── src/
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   ├── api/
│   │   │   └── api.js
│   │   ├── components/
│   │   │   ├── Navbar.jsx
│   │   │   └── ui/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── Transactions.jsx
│   │   │   ├── AddTransaction.jsx
│   │   │   ├── Budget.jsx
│   │   │   ├── Reports.jsx
│   │   │   └── CategoryManager.jsx
│   │   └── styles/
│   │       └── index.css
├── database/
│   ├── schema.sql
│   └── seed.sql
└── README.md
```

## Screenshots Placeholder

For academic report purposes, include screenshots of:
1. Login/Student selection screen
2. Dashboard with statistics and charts
3. Transactions list
4. Add transaction form
5. Budget management page
6. Reports/analytics page
7. Category management page

## Notes for Academic Submission

- All data is stored in MySQL and retrieved through Flask REST APIs
- The application demonstrates full-stack development with React frontend and Python backend
- Proper error handling and validation are implemented
- The UI uses a clean, modern design suitable for college project presentation
- Sample data is provided for immediate testing and demonstration