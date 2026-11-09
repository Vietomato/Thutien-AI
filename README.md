# ThuTien AI

An AI assistant for accounts receivable and cash flow on Odoo.
Principle: AI reads and proposes, code calculates, the accountant stays in control.
The system is read-only on Odoo.

## Quick start (demo data, no Docker needed)

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r backend/requirements.txt
    cd backend
    python -m pytest -q
    python -m uvicorn app.main:app --reload

Then open:

- http://localhost:8000/health
- http://localhost:8000/docs

On macOS or Linux, activate the environment with `source .venv/bin/activate`.

## Project layout

- `backend/app/contracts.py`: shared data contract (Invoice, Payment, Prediction, Week)
- `backend/app/odoo_reader.py`: read-only access to Odoo data
- `backend/tests/`: automated tests
- `fixtures/`: demo data for development
- `scripts/gen_fixtures.py`: regenerates the demo data
- `scripts/seed_odoo.py`: loads the demo data into Odoo
- `scripts/create_readonly_role.sql`: creates the read-only database role

Regenerate demo data:

    python scripts/gen_fixtures.py

## Odoo (local)

Port 5432 is often taken by a local PostgreSQL, so the compose file maps the
Odoo database to port 5433.

1. Start Odoo and its database:

        docker compose up -d

2. Open http://localhost:8069, create a database named `odoo`, and install the Invoicing app.

3. Load the demo data (the setup account is only used by this script):

        $env:ODOO_SETUP_USER="<your Odoo login>"
        $env:ODOO_SETUP_PASSWORD="<your Odoo password>"
        python scripts/seed_odoo.py

4. Create the read-only database role (run once):

        Get-Content scripts/create_readonly_role.sql | docker compose exec -T db psql -U odoo -d odoo

5. Check the role can log in (expect one row with a count):

        docker compose exec -e PGPASSWORD=change-me db psql -h 127.0.0.1 -U thutien_ro -d odoo -c "select count(*) from account_move;"

6. Run the API against Odoo:

        cd backend
        $env:DATA_SOURCE="odoo"; $env:ODOO_DB_PORT="5433"
        $env:ODOO_RO_USER="thutien_ro"; $env:ODOO_RO_PASSWORD="change-me"
        python -m uvicorn app.main:app --reload

Every data response contains `"source": "odoo"` or `"source": "fixture"`.
If Odoo is unreachable the API returns HTTP 502; it never falls back to demo data silently.

Never commit real passwords. Keep them in your own terminal or in `.env` (ignored by git).

## Cash-flow forecast (F4)

Receipts are predicted per open invoice (`app/prediction.py`) and summed by week for three scenarios
(`app/forecast.py`): P25 early, P50 middle, P75 late. The three lines are stress scenarios, not a
confidence interval. Expected outgoings are **typed in by the accountant**, not read from Odoo.

- `GET /api/predictions`: predicted payment dates per open invoice.
- `GET /api/f4/forecast?weeks=12`: weekly receipts, outgoings, `gap_p75` and `alerts` (weeks where late-scenario receipts are below outgoings).
- `POST /api/f4/obligations`, `GET /api/f4/obligations`: enter and list expected outgoings (accountant, manager).

Outgoings are stored in PostgreSQL (`obligations` table, created by `migrations/001_obligations.sql`). Use a PostgreSQL installed on your
machine (no Docker needed). Create the databases once, as the `postgres` user (adjust the path to your version):

    & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -f scripts/init_app_db.sql

Then copy `.env.example` to `.env` and set the `APP_DB_*` values for your machine: `APP_DB_PORT=5432` for a local
install, `APP_DB_PASSWORD` for the role you use. The app does not read `.env` by itself, so load it into your terminal first:

    Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object { $k,$v = $_ -split '=',2; Set-Item "env:$($k.Trim())" $v.Trim() }

Then create the tables and load the demo outgoings (both are safe to run again):

    python scripts/migrate.py
    python scripts/seed_obligations.py

`migrate.py` applies each numbered file in `migrations/` once and records it in `schema_migrations`. To change the
schema add a new numbered file; do not edit one that is already applied (it is detected and refused).
`seed_obligations.py` loads about a dozen simulated outgoings, one of them placed in a week where the pessimistic
scenario collects less, so the shortfall alert shows. Database contents are not stored in git: every machine runs these two commands.

Without `APP_DB_PASSWORD`, or before `migrate.py` has run, the F4 endpoints answer HTTP 503; other endpoints are unaffected.
Unit tests need no database. To also run the database round trip, point it at the throwaway test database
(the test empties the table, so it only runs when the database is named `thutien_test`):

    $env:APP_DB_NAME="thutien_test"
    python -m pytest backend/tests/test_obligations_db.py

## Team rules

- Create a `feat/...` branch from `dev` for each task.
- Open a pull request into `dev`. Never push directly to `dev` or `main`.
- Do not merge your own pull request.
- Do not change the data contract silently. Tell the people who consume it.