"""Read-only access to Odoo: supports either Odoo.com via XML-RPC API or direct PostgreSQL. Never writes."""
import os
import threading
import time
import xmlrpc.client
from datetime import date
from pathlib import Path
from typing import Any

from .contracts import Invoice, Payment

# Load .env if present
for _env_path in [Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"]:
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

try:
    import psycopg
except ImportError:
    psycopg = None

_INVOICE_SELECT = """
SELECT COALESCE(m.ref, m.id::text), COALESCE(p.ref, p.id::text), p.name,
       m.invoice_date_due, round(m.amount_total)::bigint,
       round(m.amount_residual)::bigint,
       COALESCE(m.narration::text, '') LIKE '%%[DISPUTE]%%', p.email
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


def is_xmlrpc_mode() -> bool:
    """True if configured to connect to Odoo via XML-RPC API (e.g. Odoo.com SaaS)."""
    return bool(os.getenv("ODOO_URL") and (os.getenv("ODOO_API_KEY") or os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_SETUP_PASSWORD")))


# ---------------------------------------------------------------------------
# XML-RPC implementation (for Odoo.com / SaaS)
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = 30  # Odoo.com rate-limits API calls; reads are cached briefly


class _OdooXmlRpcClient:
    def __init__(self):
        self.url = (os.getenv("ODOO_URL") or "").rstrip("/")
        if self.url.endswith("/odoo"):
            self.url = self.url[:-5]
        self.db = os.getenv("ODOO_DB") or os.getenv("ODOO_DB_NAME", "odoo")
        self.user = os.getenv("ODOO_EMAIL") or os.getenv("ODOO_USER") or os.getenv("ODOO_SETUP_USER", "")
        self.key = os.getenv("ODOO_API_KEY") or os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_SETUP_PASSWORD", "")
        self._uid = None
        self._common = None
        self._models = None
        self._lock = threading.RLock()
        self._cache: dict = {}

    def connect(self):
        if not self.url or not self.db or not self.user or not self.key:
            raise OdooUnavailable("Odoo XML-RPC credentials missing: ODOO_URL, ODOO_DB, ODOO_EMAIL, ODOO_API_KEY")
        if self._uid is not None:
            return
        try:
            self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
            self._uid = self._common.authenticate(self.db, self.user, self.key, {})
        except Exception as e:
            raise OdooUnavailable(f"cannot connect to Odoo XML-RPC: {e}") from e
        if not self._uid:
            self._uid = None
            raise OdooUnavailable("Odoo authentication failed: invalid credentials or database name")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)

    def _call(self, model: str, method: str, args: list, kwargs: dict):
        """One serialized XML-RPC call. Odoo.com rate-limits (HTTP 429), so retry with backoff, and rebuild the
        proxy after a transport error (a ServerProxy must not be shared between concurrent calls)."""
        last = None
        with self._lock:
            for attempt in range(4):
                try:
                    self.connect()
                    return self._models.execute_kw(self.db, self._uid, self.key, model, method, args, kwargs)
                except OdooUnavailable as e:
                    last = e
                except Exception as e:
                    last = e
                    self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
                time.sleep(1.5 * (attempt + 1))
        raise OdooUnavailable(f"Odoo XML-RPC {model}.{method} failed: {last}") from last

    def search_read(self, model: str, domain: list, fields: list, order: str | None = None, limit: int | None = None) -> list[dict]:
        kwargs = {}
        if order:
            kwargs["order"] = order
        if limit:
            kwargs["limit"] = limit
        key = (model, repr(domain), tuple(fields), order, limit)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
        rows = self._call(model, "search_read", [domain, fields], kwargs)
        self._cache[key] = (now, rows)
        return rows

    def execute(self, model: str, method: str, *args, **kwargs) -> Any:
        self._cache.clear()
        return self._call(model, method, list(args), kwargs)


_client = _OdooXmlRpcClient()


def _xmlrpc_partner_map() -> dict[int, dict]:
    """Helper to fetch partners mapped by ID."""
    partners = _client.search_read("res.partner", [], ["id", "name", "ref", "email"])
    return {p["id"]: p for p in partners}


def _xmlrpc_open_invoices(customer_id: str | None = None) -> list[Invoice]:
    domain = [["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["amount_residual", ">", 0]]
    inv_records = _client.search_read(
        "account.move", domain,
        ["id", "ref", "partner_id", "invoice_date_due", "amount_total", "amount_residual", "narration"],
        order="invoice_date_due asc, id asc"
    )
    if not inv_records:
        return []

    partners = _xmlrpc_partner_map()
    result = []
    for r in inv_records:
        p_id = r["partner_id"][0] if r.get("partner_id") else None
        partner = partners.get(p_id, {})
        c_id = partner.get("ref") or (str(p_id) if p_id else "")
        if customer_id and c_id != customer_id:
            continue

        inv_ref = r.get("ref") or str(r["id"])
        due = date.fromisoformat(r["invoice_date_due"]) if r.get("invoice_date_due") else None
        narration = r.get("narration") or ""
        dispute = "disputed" if "[DISPUTE]" in narration else "none"

        result.append(Invoice(
            invoice_id=inv_ref,
            customer_id=c_id,
            display_name=partner.get("name") or (r["partner_id"][1] if r.get("partner_id") else ""),
            due_date=due,
            invoice_amount=int(round(r.get("amount_total") or 0)),
            remaining_amount=int(round(r.get("amount_residual") or 0)),
            dispute_status=dispute,
            contact_email=partner.get("email") or ""
        ))
    return result


def _xmlrpc_payment_history(customer_id: str | None = None) -> list[Payment]:
    domain = [["payment_type", "=", "inbound"], ["state", "=", "posted"]]
    pays = _client.search_read(
        "account.payment", domain,
        ["id", "name", "payment_reference", "memo", "partner_id", "date", "amount", "reconciled_invoice_ids"],
        order="date asc, id asc"
    )
    if not pays:
        return []

    partners = _xmlrpc_partner_map()
    result = []
    for p in pays:
        p_id = p["partner_id"][0] if p.get("partner_id") else None
        partner = partners.get(p_id, {})
        c_id = partner.get("ref") or (str(p_id) if p_id else "")
        if customer_id and c_id != customer_id:
            continue

        p_date = date.fromisoformat(p["date"]) if p.get("date") else date.today()
        inv_ref = p.get("payment_reference") or p.get("memo") or p.get("name") or str(p["id"])
        result.append(Payment(
            payment_id=str(p["id"]),
            invoice_id=inv_ref,
            customer_id=c_id,
            payment_date=p_date,
            amount=int(round(p.get("amount") or 0))
        ))
    return result


def _xmlrpc_paid_delays(as_of_date: date | None = None) -> list[tuple[str, int]]:
    domain = [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
              ["amount_residual", "=", 0], ["invoice_date_due", "!=", False]]
    records = _client.search_read(
        "account.move", domain,
        ["id", "partner_id", "invoice_date_due", "write_date"]
    )
    partners = _xmlrpc_partner_map()
    delays = []
    for r in records:
        p_id = r["partner_id"][0] if r.get("partner_id") else None
        c_id = partners.get(p_id, {}).get("ref") or (str(p_id) if p_id else "")
        due = date.fromisoformat(r["invoice_date_due"])
        paid_on = date.fromisoformat(r["write_date"][:10])
        if as_of_date is not None and paid_on > as_of_date:
            continue
        diff_days = (paid_on - due).days
        delays.append((c_id, diff_days))
    return delays


def _xmlrpc_supplier_bills() -> list[tuple[date, int]]:
    domain = [["move_type", "=", "in_invoice"], ["state", "=", "posted"],
              ["amount_residual", ">", 0], ["invoice_date_due", "!=", False]]
    records = _client.search_read(
        "account.move", domain,
        ["invoice_date_due", "amount_residual"], order="invoice_date_due asc"
    )
    return [(date.fromisoformat(r["invoice_date_due"]), int(round(r["amount_residual"]))) for r in records]


def _xmlrpc_customers() -> list[dict]:
    domain = [["move_type", "=", "out_invoice"], ["state", "=", "posted"]]
    invs = _client.search_read("account.move", domain, ["partner_id"])
    partner_ids = list({r["partner_id"][0] for r in invs if r.get("partner_id")})
    if not partner_ids:
        return []
    records = _client.search_read("res.partner", [["id", "in", partner_ids]], ["id", "ref", "name"])
    return [{"customer_id": r.get("ref") or str(r["id"]), "name": r["name"]} for r in records]


# ---------------------------------------------------------------------------
# PostgreSQL implementation (for local Docker / self-hosted DB)
# ---------------------------------------------------------------------------

def _connect():
    if psycopg is None:
        raise OdooUnavailable("psycopg is not installed for direct database access")
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
                   dispute_status="disputed" if r[6] else "none", contact_email=r[7])


# ---------------------------------------------------------------------------
# Public Facade (switches between XML-RPC and PostgreSQL automatically)
# ---------------------------------------------------------------------------

def open_invoices(customer_id: str | None = None) -> list[Invoice]:
    """Open invoices. With customer_id, only that customer's."""
    if is_xmlrpc_mode():
        return _xmlrpc_open_invoices(customer_id)
    if customer_id is None:
        rows = _query(_INVOICE_SELECT.format(extra=""))
    else:
        rows = _query(_INVOICE_SELECT.format(extra=f"AND {_CUST_ID} = %s"), [customer_id])
    return [_invoice(r) for r in rows]


def open_invoice(invoice_id: str) -> Invoice | None:
    if is_xmlrpc_mode():
        all_invs = _xmlrpc_open_invoices()
        for inv in all_invs:
            if inv.invoice_id == invoice_id:
                return inv
        return None
    rows = _query(_INVOICE_SELECT.format(extra=f"AND {_INV_ID} = %s"), [invoice_id])
    return _invoice(rows[0]) if rows else None


def payment_history(customer_id: str | None = None) -> list[Payment]:
    if is_xmlrpc_mode():
        return _xmlrpc_payment_history(customer_id)
    if customer_id is None:
        rows = _query(_PAYMENT_SELECT.format(extra=""))
    else:
        rows = _query(_PAYMENT_SELECT.format(extra="AND COALESCE(pt.ref, pt.id::text) = %s"), [customer_id])
    return [Payment(payment_id=r[0], invoice_id=r[1], customer_id=r[2], payment_date=r[3], amount=r[4])
            for r in rows]


def paid_delays(as_of_date: date | None = None) -> list[tuple[str, int]]:
    """(customer_id, days late) for every fully paid invoice. Input for payment predictions."""
    if is_xmlrpc_mode():
        return _xmlrpc_paid_delays(as_of_date)
    sql = _DELAYS_SQL
    params = None
    if as_of_date is not None:
        sql += " HAVING max(pr.max_date)::date <= %s"
        params = [as_of_date]
    return [(r[0], int(r[1])) for r in _query(sql, params)]


def supplier_bills() -> list[tuple[date, int]]:
    """(due date, amount) of supplier bills still unpaid."""
    if is_xmlrpc_mode():
        return _xmlrpc_supplier_bills()
    return [(r[0], int(r[1])) for r in _query(_BILLS_SQL)]


def customers() -> list[dict]:
    if is_xmlrpc_mode():
        return _xmlrpc_customers()
    return [{"customer_id": r[0], "name": r[1]} for r in _query(_CUSTOMERS_SQL)]
