"""Check the connection to Odoo through its API and show what the app would read. Read-only.

    python scripts/check_odoo_api.py

Needs ODOO_URL, ODOO_DB_NAME and ODOO_API_KEY in your terminal (see .env.example).
Prints counts only: no secrets, no customer data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import odoo_api_reader as reader  # noqa: E402
from app.odoo_reader import OdooUnavailable  # noqa: E402

try:
    invoices = reader.all_invoices()
    payments = reader.payment_history()
except OdooUnavailable as e:
    sys.exit(f"FAILED: {e}")

open_ = [i for i in invoices if i.remaining_amount > 0]
print("login OK")
print(f"invoices read : {len(invoices)} ({len(open_)} still open, {len(invoices) - len(open_)} paid)")
print(f"payments read : {len(payments)}")
print(f"customers     : {len({i.customer_id for i in invoices})}")
if invoices:
    print(f"due dates     : {min(i.due_date for i in invoices)} to {max(i.due_date for i in invoices)}")
if not invoices:
    print("No posted customer invoices found. The database is empty or the user cannot see them.")
