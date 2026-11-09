# ThuTien AI

An assistant for accounts receivable and cash flow on Odoo.
Principle: the system reads and calculates, the accountant stays in control.
The system is read-only on Odoo: nothing is ever written to it.

## How the data is organised

- **Odoo database** (read-only): customers, invoices, payments, supplier bills. Every business number comes from here.
- **Application database** (`thutien_app`, PostgreSQL): users and roles, reminder drafts, collection tasks, audit log.
- Predictions and the 12-week cash forecast are computed from Odoo's real payment history
  (`backend/app/analytics.py`). There is no mock or fixture data at runtime.

## Roles and permissions

| | Nhân viên kế toán | Kế toán trưởng | Khách hàng | Admin |
|---|---|---|---|---|
| Invoices, payments, summary | all | all | own only | no |
| Payment predictions, 12-week forecast | yes | yes | no | no |
| Write reminder drafts | yes | yes | no | no |
| Approve or reject drafts | no | yes | no | no |
| Own collection tasks | yes | yes | no | no |
| Team's tasks, assign tasks | no | yes | no | no |
| Users, roles, audit log | no | no | no | yes |

- A chief accountant supervises accountants (set by the admin). They see the team's drafts and tasks only.
- A customer account is linked to one Odoo customer id and sees only that customer's invoices and payments.
- Self-registered accounts are customers linked to nothing, so they see no data until an admin links them.
- The matrix lives in `backend/app/permissions.py`; endpoints check permissions, not role names. Role and
  active flag are read from the database on every request, so a change applies immediately.
- Passwords are hashed (scrypt). After 5 wrong passwords an account is locked for 15 minutes.
- The audit log is append-only (a database trigger blocks UPDATE and DELETE) and masks passwords and tokens.
- Approving a draft only records the decision. The system has no email sender, so nothing is delivered.

## Setup

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r backend/requirements.txt

### 1. Databases (Docker)

Port 5432 is often taken by a local PostgreSQL, so the compose file maps Postgres to port 5433.

    docker compose up -d

1. Open http://localhost:8069, create a database named `odoo`, install the Invoicing app.
2. Load the demo invoices into Odoo (the setup account is only used by this script):

        $env:ODOO_SETUP_USER="<your Odoo login>"
        $env:ODOO_SETUP_PASSWORD="<your Odoo password>"
        python scripts/seed_odoo.py

3. Create the read-only Odoo role (run once):

        Get-Content scripts/create_readonly_role.sql | docker compose exec -T db psql -U odoo -d odoo

4. Create the application database and role (run once):

        Get-Content scripts/init_app_db.sql | docker compose exec -T db psql -U odoo -d postgres

### 2. Environment

Set these in your terminal, or keep them in `.env` (ignored by git). See `.env.example` for all names.

    $env:APP_DB_PASSWORD="change-me"
    $env:ODOO_DB_PORT="5433"; $env:ODOO_RO_USER="thutien_ro"; $env:ODOO_RO_PASSWORD="change-me"
    $env:JWT_SECRET="<a long random string>"

Never commit real passwords.

### 3. Demo accounts

Tables are created on first start. Then create one account per role (password from `DEMO_PASSWORD`, at least 8 characters):

    $env:DEMO_PASSWORD="<choose one>"
    python scripts/seed_users.py

This creates `chief1`, `accountant1`, `accountant2` (both in chief1's team), `customer1` (linked to Odoo customer C001) and `admin1`.
Use the admin screen to create real accounts, link customers and change roles.

### 4. Run

    cd backend
    python -m uvicorn app.main:app --reload

- Web app: http://localhost:8000/app/
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health (shows whether the application database is reachable)

If Odoo is unreachable the API returns 502; if the application database is unreachable it returns 503.
It never falls back to made-up data.

## Tests

    cd backend
    $env:APP_DB_PASSWORD="change-me"
    $env:ODOO_DB_PORT="5433"; $env:ODOO_RO_USER="thutien_ro"; $env:ODOO_RO_PASSWORD="change-me"
    python -m pytest -q

API tests use the `thutien_test` database (created by `init_app_db.sql`; its tables are emptied between tests)
and never touch `thutien_app`. Permission and workflow tests replace Odoo with an in-memory fake so the expected
data is known. `test_odoo_integration.py` reads the real Odoo database and is skipped when it is not configured.

## Project layout

- `backend/app/permissions.py`: roles and the permission matrix
- `backend/app/auth.py`, `users.py`, `security.py`: login, registration, lockout, password hashing
- `backend/app/odoo_reader.py`: read-only queries on Odoo
- `backend/app/analytics.py`: predictions, forecast, summary (pure functions)
- `backend/app/routes_*.py`: API (data, reminders, tasks, admin)
- `backend/app/schema.sql`, `db.py`, `audit.py`, `drafts.py`, `tasks.py`: application database
- `backend/tests/`: automated tests
- `frontend/`: web app in plain HTML/CSS/JS, served at `/app/`
- `fixtures/`, `scripts/gen_fixtures.py`, `scripts/seed_odoo.py`: demo data that is loaded into Odoo
- `scripts/create_readonly_role.sql`, `init_app_db.sql`, `seed_users.py`: setup helpers

## Supplier bills and the cash forecast

"Phải chi" in the forecast is the unpaid supplier bills in Odoo (vendor bills with a due date). If Odoo has none,
obligations are 0 and no week is flagged as short; the dashboard says so.

## Team rules

- Create a `feat/...` branch from `dev` for each task.
- Open a pull request into `dev`. Never push directly to `dev` or `main`.
- Do not merge your own pull request.
- Do not change the data contract silently. Tell the people who consume it.
