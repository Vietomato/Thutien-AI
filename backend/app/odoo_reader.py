"""Read-only Odoo data. Local PostgreSQL or Odoo Online JSON-2, selected by env."""
import os
from datetime import date

import psycopg

from . import odoo_online
from .contracts import Invoice, Payment

_INVOICE_SELECT = """
SELECT COALESCE(m.ref, m.id::text), COALESCE(p.ref, p.id::text), p.name,
       m.invoice_date_due, round(m.amount_total)::bigint,
       round(m.amount_residual)::bigint,
       COALESCE(m.narration::text, '') LIKE '%%[DISPUTE]%%', p.email,
       m.write_date::text
FROM account_move m JOIN res_partner p ON p.id = m.partner_id
WHERE m.move_type = 'out_invoice' AND m.state = 'posted'
  AND m.amount_residual > 0 {extra}
ORDER BY m.invoice_date_due, m.id
"""

_PAYMENT_SELECT = """
SELECT pr.id::text, COALESCE(inv.ref, inv.id::text), COALESCE(pt.ref, pt.id::text),
       pr.max_date, round(pr.amount)::bigint
FROM account_partial_reconcile pr
JOIN account_move_line dl ON dl.id = pr.debit_move_id
JOIN account_move inv ON inv.id = dl.move_id
JOIN res_partner pt ON pt.id = inv.partner_id
WHERE inv.move_type = 'out_invoice' AND inv.state = 'posted' {extra}
ORDER BY pr.max_date, pr.id
"""

# Days between due date and the last payment of each fully paid invoice (negative = paid early).
_DELAYS_SQL = """
SELECT COALESCE(p.ref, p.id::text), (max(pr.max_date)::date - m.invoice_date_due)
FROM account_move m
JOIN res_partner p ON p.id = m.partner_id
JOIN account_move_line dl ON dl.move_id = m.id
JOIN account_partial_reconcile pr ON pr.debit_move_id = dl.id
WHERE m.move_type = 'out_invoice' AND m.state = 'posted'
  AND m.amount_residual = 0 AND m.invoice_date_due IS NOT NULL
GROUP BY m.id, p.id, m.invoice_date_due
"""

# Supplier bills still to pay: the money going out (obligations).
_BILLS_SQL = """
SELECT m.invoice_date_due, round(m.amount_residual)::bigint
FROM account_move m
WHERE m.move_type = 'in_invoice' AND m.state = 'posted'
  AND m.amount_residual > 0 AND m.invoice_date_due IS NOT NULL
ORDER BY m.invoice_date_due
"""

_CUSTOMERS_SQL = """
SELECT DISTINCT COALESCE(p.ref, p.id::text), p.name
FROM res_partner p
WHERE EXISTS (SELECT 1 FROM account_move m WHERE m.partner_id = p.id
              AND m.move_type = 'out_invoice' AND m.state = 'posted')
ORDER BY 1
"""

_INV_ID = "COALESCE(m.ref, m.id::text)"
_CUST_ID = "COALESCE(p.ref, p.id::text)"


class OdooUnavailable(Exception):
    pass


def _online() -> bool:
    source = os.getenv("ODOO_SOURCE", "local_db").strip().lower()
    if source not in ("local_db", "online"):
        raise OdooUnavailable("ODOO_SOURCE must be local_db or online")
    return source == "online"


def _cloud(method: str, *args):
    try:
        return getattr(odoo_online, method)(*args)
    except odoo_online.OdooOnlineError as exc:
        raise OdooUnavailable(str(exc)) from None


def _connect():
    try:
        return psycopg.connect(
            host=os.getenv("ODOO_DB_HOST", "localhost"),
            port=int(os.getenv("ODOO_DB_PORT", "5432")),
            dbname=os.getenv("ODOO_DB_NAME", "odoo"),
            user=os.getenv("ODOO_RO_USER", "thutien_ro"),
            password=os.getenv("ODOO_RO_PASSWORD"),
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
        )
    except psycopg.Error as e:
        raise OdooUnavailable(f"cannot connect to Odoo DB: {e}") from e


def _query(sql: str, params: list | None = None) -> list[tuple]:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params or None)
            return cur.fetchall()
    except psycopg.Error as e:
        raise OdooUnavailable(f"Odoo query failed: {e}") from e


def _invoice(r) -> Invoice:
    return Invoice(invoice_id=r[0], customer_id=r[1], display_name=r[2], due_date=r[3],
                   invoice_amount=r[4], remaining_amount=r[5],
                   dispute_status="disputed" if r[6] else "none", contact_email=r[7],
                   source_version=r[8])


def open_invoices(customer_id: str | None = None) -> list[Invoice]:
    """Open invoices. With customer_id, only that customer's (the filter is applied in SQL)."""
    if _online():
        return _cloud("open_invoices", customer_id)
    if customer_id is None:
        rows = _query(_INVOICE_SELECT.format(extra=""))
    else:
        rows = _query(_INVOICE_SELECT.format(extra=f"AND {_CUST_ID} = %s"), [customer_id])
    return [_invoice(r) for r in rows]


def open_invoice(invoice_id: str) -> Invoice | None:
    if _online():
        return _cloud("open_invoice", invoice_id)
    rows = _query(_INVOICE_SELECT.format(extra=f"AND {_INV_ID} = %s"), [invoice_id])
    return _invoice(rows[0]) if rows else None


def payment_history(customer_id: str | None = None) -> list[Payment]:
    if _online():
        return _cloud("payment_history", customer_id)
    if customer_id is None:
        rows = _query(_PAYMENT_SELECT.format(extra=""))
    else:
        rows = _query(_PAYMENT_SELECT.format(extra="AND COALESCE(pt.ref, pt.id::text) = %s"), [customer_id])
    return [Payment(payment_id=r[0], invoice_id=r[1], customer_id=r[2], payment_date=r[3], amount=r[4])
            for r in rows]


def paid_delays(as_of_date: date | None = None) -> list[tuple[str, int]]:
    """(customer_id, days late) for fully paid invoices settled by the calculation date."""
    if _online():
        return _cloud("paid_delays", as_of_date)
    sql = _DELAYS_SQL
    params = None
    if as_of_date is not None:
        sql += " HAVING max(pr.max_date)::date <= %s"
        params = [as_of_date]
    return [(r[0], int(r[1])) for r in _query(sql, params)]


def supplier_bills() -> list[tuple[date, int]]:
    """(due date, amount) of supplier bills still unpaid."""
    if _online():
        return _cloud("supplier_bills")
    return [(r[0], int(r[1])) for r in _query(_BILLS_SQL)]


def customers() -> list[dict]:
    if _online():
        return _cloud("customers")
    return [{"customer_id": r[0], "name": r[1]} for r in _query(_CUSTOMERS_SQL)]
