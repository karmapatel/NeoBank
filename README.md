# NeoBank - Next-Gen Digital Banking Platform

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.0-black.svg?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%2B-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Supabase](https://img.shields.io/badge/Supabase-Supported-3ECF8E.svg?logo=supabase&logoColor=white)](https://supabase.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-d71f00.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md)

**NeoBank** is a modern, full-stack digital banking web application built with **Flask**, **SQLAlchemy**, and **Supabase (PostgreSQL)**. It features high-yield savings accounts, virtual debit cards with real-time controls, instant money transfers with live account lookup, an intelligent loan underwriting engine, customizable savings vaults, and an autonomous midnight banking engine for automated daily interest accruals and loan EMI debits.

---

## Key Features

### 1. Account Management & Real-Time Balances
- **Multi-Account Support**: Manage both liquid Checking and high-yield Savings accounts under a single profile.
- **Detailed Account Views**: View historical statement records, transaction breakdowns, and account numbers.
- **Account Opening Wizard**: Instantly open new checking, savings, fixed-deposit, or business accounts.

### 2. Virtual Cards & Security Controls
- **Virtual Debit Cards**: Instant issue of RuPay Platinum and Visa Platinum cards.
- **Cardholder Security**: Dynamic CVV toggle reveal, one-tap card freeze/unfreeze, and custom daily spending limits.
- **Multi-factor Transaction PIN**: 4-digit PIN verification required for fund transfers and card operations.

### 3. Smart Transfers & Fast Account Lookup
- **Instant P2P Transfers**: Move funds between internal accounts or send money to external bank beneficiaries.
- **Real-Time Recipient Validation**: Instant API lookups by account number or username with automatic recipient badge rendering.
- **Beneficiary Directory**: Save frequent payees for frictionless one-click fund transfers.

### 4. Autonomous 12:00 AM Midnight Banking Daemon
- **Automated Interest Accrual**: Daily background engine automatically credits interest to active accounts (Savings @ 6.5%, FD @ 7.25%, Checking @ 3.5%, Business @ 4.0% p.a.).
- **Auto-Debit EMI Engine**: Automatically evaluates and deducts monthly loan installments on due dates.
- **Idempotent Execution**: Guaranteed exactly-once daily batch execution tracked via system audit states.

### 5. Loans & Credit Underwriting
- **Credit Evaluation**: Real-time eligibility calculation factoring in CIBIL credit score and verifiable monthly income.
- **Customizable Tenures**: Flexible loan amounts and repayment periods (6 to 60 months) with live EMI and amortization previews.
- **Instant Disbursement**: Approved loans credit directly into the primary checking account.

### 6. Savings Vaults & Financial Goals
- **Dedicated Target Vaults**: Create savings goals with customizable target amounts, deadlines, icons, and color accents.
- **Interactive Progress Trackers**: Live percentage completion gauges and easy deposit/withdraw actions.

### 7. Security, Auditing & Statement Export
- **Comprehensive Audit Logs**: Every login, transaction, card toggle, and PIN change is logged with timestamp and IP address.
- **CSV Statement Exports**: Filter transactions by date or category and download official CSV ledger records.

---

## Architecture & Tech Stack

```mermaid
graph TD
    Client[Browser / Modern UI] -->|HTTP / REST| FlaskApp[Flask 3.0 Core Engine]
    FlaskApp -->|Auth / Session| Security[Werkzeug & PIN Auth]
    FlaskApp -->|Background Thread| Daemon[12:00 AM Midnight Banking Engine]
    FlaskApp -->|ORM / Pooling| SQLAlchemy[SQLAlchemy 2.0]
    SQLAlchemy -->|psycopg2 / Pooler| Supabase[(Supabase PostgreSQL 17)]
    SQLAlchemy -.->|Local Fallback| SQLite[(SQLite neobank.db)]
```

- **Backend**: Python 3.10+, Flask 3.0, Werkzeug 3.1
- **Database & ORM**: Supabase Managed PostgreSQL (via `psycopg2-binary` & SQLAlchemy) with automatic fallback to SQLite
- **Connection Optimization**: Built-in connection pooling (`pool_pre_ping=True`, `pool_recycle=300`) for Supabase PgBouncer pooler stability
- **Frontend**: Responsive Vanilla CSS, Semantic HTML5, Font Awesome, Google Fonts (Inter / Outfit)
- **Environment Management**: `python-dotenv`

---

## Project Structure

```
Banking/
├── app.py                      # Core Flask application, routing, and midnight engine
├── models.py                   # SQLAlchemy models (User, Account, Transaction, Loan, etc.)
├── seed.py                     # Database seeding script with realistic INR demo data
├── supabase_client.py          # Database URI resolver, pooling configuration, and Supabase client
├── test_supabase_connection.py # Diagnostic utility for verifying database connectivity
├── test_app.py                 # Automated test suite (28 unit tests)
├── requirements.txt            # Python dependencies
├── .env.example                # Configuration template with Supabase guide
├── .env                        # Local environment file (ignored by git)
├── .gitignore                  # Git exclusion rules
├── templates/                  # Jinja2 HTML templates
│   ├── auth/                   # Login and Registration screens
│   ├── base.html               # Master layout template
│   ├── dashboard.html          # Main banking dashboard
│   ├── accounts.html           # Accounts listing & management
│   ├── account_detail.html     # Statement view for an account
│   ├── transfer.html           # Fund transfer interface
│   ├── cards.html              # Virtual cards interface
│   ├── loans.html              # Loan application & repayments
│   ├── vaults.html             # Savings goals
│   └── transactions.html       # Transaction history and CSV exports
└── static/                     # CSS stylesheets, client-side JS, and images
```

---

## Getting Started

### Prerequisites
- **Python 3.10+**
- **Git**
- A free **[Supabase](https://supabase.com)** account (or run locally using the default SQLite fallback)

### 1. Clone the Repository
```bash
git clone https://github.com/karmapatel/NeoBank.git
cd NeoBank
```

### 2. Set Up a Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## Database Configuration (Supabase or SQLite)

### Option A: Connect to Supabase (Recommended)

1. Go to your [Supabase Dashboard](https://app.supabase.com) and open your project.
2. Navigate to **Project Settings** (gear icon) -> **Database** -> **Connection string**.
3. Under the **URI** tab, copy your connection string (Direct or Connection Pooler).
4. Copy the environment template:
   ```bash
   cp .env.example .env
   ```
5. Edit `.env` and paste your connection string:
   ```env
   DATABASE_URL=postgresql://postgres:[YOUR-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
   ```
   *(Or use the Supabase connection pooler on port 6543 / 5432).*

6. **Verify your connection**:
   ```bash
   python test_supabase_connection.py
   ```
   You should see:
   ```text
   [OK] Connection established successfully!
   [OK] Database Version: PostgreSQL 17...
   ```

### Option B: Local SQLite (Zero Configuration)
If `DATABASE_URL` is left empty or commented out in `.env`, NeoBank automatically uses a local SQLite database (`instance/neobank.db`).

---

## Database Seeding & Running

### 1. Initialize Tables and Demo Data
Run the seeding script to create database tables and populate demo accounts:
```bash
python seed.py
```

### 2. Start the Development Server
```bash
python app.py
```
Open your browser and navigate to: **http://127.0.0.1:5000**

---

## Demo Credentials

You can log in with either of the following pre-seeded demo accounts:

| Role | Username | Password | Transaction PIN | Initial Checking |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Customer** | `alex.mercer` | `password123` | `1234` | ₹1,42,500.00 |
| **Secondary Customer**| `sarah.chen` | `password123` | `1234` | ₹85,000.00 |

---

## Testing & Diagnostics

### Run the Diagnostic Tool
Inspect your database connection, PostgreSQL version, and table record counts:
```bash
python test_supabase_connection.py
```

### Run the Automated Test Suite
Execute the 28 unit tests covering authentication, transfers, loans, cards, and daily interest cycles:
```bash
python -m unittest test_app.py
```

---

## Security Highlights

- **Hashed Passwords**: Password hashing via Werkzeug `generate_password_hash` with secure salting.
- **Connection Isolation**: `.gitignore` strictly protects `.env`, local `.db` files, and secrets from being committed.
- **SQLAlchemy ORM**: Full parameterization protects against SQL injection attacks.
- **Connection Resilience**: Built-in engine pinging and recycling (`pool_pre_ping=True`, `pool_recycle=300`) prevent dropped sockets when connected to serverless PostgreSQL.

---

## Contributing

Contributions, issues, and feature requests are welcome!
1. Fork the project.
2. Create your feature branch (`git checkout -b feature/AmazingFeature`).
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4. Push to the branch (`git push origin feature/AmazingFeature`).
5. Open a Pull Request.

---

## License

Distributed under the MIT License. See `LICENSE.md` for more information.
