    # ThuTien AI

An AI assistant for accounts receivable and cash flow on Odoo.
Principle: AI reads and proposes, code calculates, the accountant stays in control.
The system is read-only on Odoo.

## Quick start

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
- `backend/tests/`: automated tests
- `fixtures/`: demo data for development
- `scripts/gen_fixtures.py`: regenerates the demo data

Regenerate demo data:

    python scripts/gen_fixtures.py

## Team rules

- Create a `feat/...` branch from `dev` for each task.
- Open a pull request into `dev`. Never push directly to `dev` or `main`.
- Do not merge your own pull request.
- Do not change the data contract silently. Tell the people who consume it.