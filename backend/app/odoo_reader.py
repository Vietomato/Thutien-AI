"""Read-only Odoo data. Local PostgreSQL or Odoo Online JSON-2, selected by env."""
import copy
import logging
import os
import threading
import time
from datetime import date, datetime, timezone

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


def _fetch(method: str, *args):
    try:
        return getattr(odoo_online, method)(*args)
    except odoo_online.OdooOnlineError as exc:
        raise OdooUnavailable(str(exc)) from None


# Odoo Online is read over the internet (0.5 to 2 s a call) and one page load asks for the same lists many times, so reads are
# kept in memory. Behaviour:
#   * fresh   (age < ttl):          returned at once.
#   * stale   (ttl <= age < limit): returned at once, and ONE background thread reads Odoo again. Nobody waits for Odoo.
#   * missing or too old:           the first request reads Odoo; concurrent requests for the same list wait for that one read.
# A failed refresh keeps the old data (retried after 15 s) until `limit`, so a short Odoo outage does not stop the app.
# ODOO_CACHE_SECONDS (default 120, 0 = off) is the freshness of the fast-changing lists; payment history and customers change
# slowly and are kept 5 times longer. A single invoice (open_invoice) is never cached: approving a reminder must see the debt
# as it is now. The local database is fast and is not cached.
_FACTOR = {"open_invoices": 1, "supplier_bills": 1, "paid_delays": 5, "payment_history": 5, "customers": 5}
_LIMIT_FACTOR = 10
_RETRY_AFTER = 15.0
_CACHE: dict[tuple, tuple[float, float, object]] = {}      # key -> (monotonic time, wall-clock time, value)
_LOCKS: dict[tuple, threading.Lock] = {}
_REFRESHING: set[tuple] = set()
_NEXT_TRY: dict[tuple, float] = {}
_GUARD = threading.Lock()
_log = logging.getLogger("thutien.cache")


def _cache_seconds() -> float:
    try:
        return max(float(os.getenv("ODOO_CACHE_SECONDS", "120")), 0.0)
    except ValueError:
        return 120.0


def _ttl(method: str) -> float:
    return _cache_seconds() * _FACTOR.get(method, 0)


def clear_cache() -> None:
    """Forget everything read from Odoo, so the next request reads fresh data (the "reload" button)."""
    with _GUARD:
        _CACHE.clear()
        _NEXT_TRY.clear()
    odoo_online.clear_cache()


def data_updated_at() -> str:
    """When the invoice, payment and bill lists in memory were read from Odoo (the oldest of them), as an ISO time."""
    walls = [entry[1] for key, entry in list(_CACHE.items()) if key[0] in ("open_invoices", "paid_delays", "supplier_bills")]
    return datetime.fromtimestamp(min(walls) if walls else time.time(), timezone.utc).isoformat(timespec="seconds")


def _store(key: tuple, value) -> None:
    _CACHE[key] = (time.monotonic(), time.time(), value)
    _NEXT_TRY.pop(key, None)


def _refresh(key: tuple) -> None:
    try:
        _store(key, _fetch(key[0], *key[1]))
    except Exception as exc:                                  # keep serving the old data; try again later
        _NEXT_TRY[key] = time.monotonic() + _RETRY_AFTER
        _log.warning("background refresh of %s failed: %s", key[0], exc)
    finally:
        with _GUARD:
            _REFRESHING.discard(key)


def _cloud(method: str, *args):
    ttl = _ttl(method)
    if ttl <= 0:
        return _fetch(method, *args)
    key = (method, args)
    entry = _CACHE.get(key)
    now = time.monotonic()
    if entry:
        age = now - entry[0]
        if age < ttl:
            return copy.deepcopy(entry[2])
        if age < ttl * _LIMIT_FACTOR:                          # stale: answer now, refresh behind the scenes
            with _GUARD:
                start = key not in _REFRESHING and now >= _NEXT_TRY.get(key, 0.0)
                if start:
                    _REFRESHING.add(key)
            if start:
                threading.Thread(target=_refresh, args=(key,), daemon=True, name=f"refresh-{method}").start()
            return copy.deepcopy(entry[2])
    with _GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        entry = _CACHE.get(key)                                 # another request may have filled it while we waited
        if entry and time.monotonic() - entry[0] < ttl:
            return copy.deepcopy(entry[2])
        value = _fetch(method, *args)
        _store(key, value)
    return copy.deepcopy(value)


def warm_cache() -> None:
    """Read the main lists once, in parallel, so the first visitor does not wait for Odoo. Never raises."""
    if not _online() or _cache_seconds() <= 0:
        return
    from concurrent.futures import ThreadPoolExecutor
    from .config import as_of_date
    jobs = [lambda: open_invoices(), lambda: paid_delays(as_of_date()), supplier_bills, customers]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        for future in [pool.submit(job) for job in jobs]:
            try:
                future.result()
            except Exception as exc:
                _log.warning("cache warm-up failed: %s", exc)


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
        items = _cloud("open_invoices", None)                 # one cached list serves every customer's view
        return [i for i in items if i.customer_id == customer_id] if customer_id is not None else items
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
        items = _cloud("payment_history", None)
        return [p for p in items if p.customer_id == customer_id] if customer_id is not None else items
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
