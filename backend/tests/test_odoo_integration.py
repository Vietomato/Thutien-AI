"""Reads the REAL Odoo database (read-only). Skipped when Odoo is not configured or not reachable.
Needs ODOO_DB_PORT, ODOO_RO_USER and ODOO_RO_PASSWORD, and the demo data loaded by scripts/seed_odoo.py."""
import os

import pytest

from app import odoo_reader

pytestmark = pytest.mark.skipif(not os.getenv("ODOO_RO_USER"), reason="Odoo read-only account not configured")


@pytest.fixture(scope="module")
def invoices():
    try:
        return odoo_reader.open_invoices()
    except odoo_reader.OdooUnavailable as e:
        pytest.skip(f"Odoo not reachable: {e}")


def test_open_invoices_come_from_odoo(invoices):
    assert invoices and all(i.remaining_amount > 0 for i in invoices)


def test_customer_filter_is_applied_in_sql(invoices):
    cid = invoices[0].customer_id
    only = odoo_reader.open_invoices(cid)
    assert only and {i.customer_id for i in only} == {cid}
    assert len(only) <= len(invoices)
    assert odoo_reader.open_invoices("NO-SUCH-CUSTOMER") == []


def test_single_invoice_lookup(invoices):
    first = invoices[0]
    assert odoo_reader.open_invoice(first.invoice_id).remaining_amount == first.remaining_amount
    assert odoo_reader.open_invoice("NO-SUCH-INVOICE") is None


def test_payment_history_and_delays():
    pays = odoo_reader.payment_history()
    assert pays and all(p.amount > 0 for p in pays)
    delays = odoo_reader.paid_delays()
    assert delays and all(isinstance(d, int) for _, d in delays)


def test_customers_and_bills_queries_run():
    assert odoo_reader.customers()
    assert isinstance(odoo_reader.supplier_bills(), list)


def test_connection_is_read_only():
    with odoo_reader._connect() as conn, conn.cursor() as cur:
        with pytest.raises(Exception):
            cur.execute("CREATE TABLE should_not_exist (x int)")
