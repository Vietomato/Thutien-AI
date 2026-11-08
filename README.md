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

## Team rules

- Create a `feat/...` branch from `dev` for each task.
- Open a pull request into `dev`. Never push directly to `dev` or `main`.
- Do not merge your own pull request.
- Do not change the data contract silently. Tell the people who consume it.