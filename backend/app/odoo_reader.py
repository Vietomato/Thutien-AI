import os
import psycopg
from .contracts import Invoice, Payment

INVOICES_SQL = """
SELECT COALESCE(m.ref, m.id::text), COALESCE(p.ref, p.id::text), p.name,
       m.invoice_date_due, round(m.amount_total)::bigint,
       round(m.amount_residual)::bigint,
       COALESCE(m.narration::text, '') LIKE '%%[DISPUTE]%%', p.email
FROM account_move m JOIN res_partner p ON p.id = m.partner_id
WHERE m.move_type = 'out_invoice' AND m.state = 'posted'
  AND m.amount_residual > 0
ORDER BY m.invoice_date_due, m.id
"""

PAYMENTS_SQL = """
SELECT pr.id::text, COALESCE(inv.ref, inv.id::text), COALESCE(pt.ref, pt.id::text),
       pr.max_date, round(pr.amount)::bigint
FROM account_partial_reconcile pr
JOIN account_move_line dl ON dl.id = pr.debit_move_id
JOIN account_move inv ON inv.id = dl.move_id
JOIN res_partner pt ON pt.id = inv.partner_id
WHERE inv.move_type = 'out_invoice' AND inv.state = 'posted'
ORDER BY pr.max_date, pr.id
"""


class OdooUnavailable(Exception):
    pass


def _connect():
    try:
        return psycopg.connect(
            host=os.getenv("ODOO_DB_HOST", "localhost"),
            port=int(os.getenv("ODOO_DB_PORT", "5432")),
            dbname=os.getenv("ODOO_DB_NAME", "odoo"),
            user=os.getenv("ODOO_RO_USER"),
            password=os.getenv("ODOO_RO_PASSWORD"),
            connect_timeout=5,
            options="-c default_transaction_read_only=on",
        )
    except psycopg.Error as e:
        raise OdooUnavailable(f"cannot connect to Odoo DB: {e}") from e


def open_invoices() -> list[Invoice]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(INVOICES_SQL)
        return [
            Invoice(invoice_id=r[0], customer_id=r[1], display_name=r[2], due_date=r[3],
                    invoice_amount=r[4], remaining_amount=r[5],
                    dispute_status="disputed" if r[6] else "none", contact_email=r[7])
            for r in cur.fetchall()
        ]


def payment_history() -> list[Payment]:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(PAYMENTS_SQL)
        return [Payment(payment_id=r[0], invoice_id=r[1], customer_id=r[2],
                        payment_date=r[3], amount=r[4]) for r in cur.fetchall()]