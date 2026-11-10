"""Read-only access to Odoo through its external API.

For hosted Odoo (for example Odoo.com) that does not expose the PostgreSQL database. It offers the same
functions and returns the same contract types as odoo_reader.py (the SQL reader).

Two transports, chosen with ODOO_API_TRANSPORT:
  json2   (default) the JSON-2 API of Odoo 19 and later: POST /json/2/<model>/<method>, bearer API key.
  xmlrpc  the older XML-RPC API (Odoo up to 18; deprecated in newer versions).

Read-only by construction: only the methods in READ_METHODS can be called, anything else is refused before
a request is made. Settings come from the environment; nothing is stored in the code:

    ODOO_URL            https://yourcompany.odoo.com   (a pasted browser address is cut down to scheme and host)
    ODOO_DB_NAME        database name (for Odoo.com it is usually the sub-domain)
    ODOO_API_KEY        API key (profile > Account Security > New API Key)
    ODOO_API_USER       login of the key's user; only needed for the xmlrpc transport
    ODOO_API_TRANSPORT  json2 (default) or xmlrpc
"""
import json
import logging
import os
import urllib.error
import urllib.request
import xmlrpc.client
from urllib.parse import urlsplit

from .contracts import Invoice, Payment
from .odoo_reader import OdooUnavailable

log = logging.getLogger("thutien.odoo_api")

READ_METHODS = frozenset({"search_read", "read", "search_count"})
FIRST_ARG = {"search_read": "domain", "search_count": "domain", "read": "ids"}   # xmlrpc takes it positionally
PAGE = 500
TIMEOUT = 20

_MOVE_FIELDS = ["ref", "partner_id", "invoice_date_due", "invoice_date", "amount_total", "amount_residual", "narration"]


# ---------- settings and error text ----------
def _origin(url: str) -> str:
    """Keep scheme and host only. Odoo's API lives at the root, but people paste the browser address
    (https://x.odoo.com/odoo), so any path after the host is dropped."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def _settings() -> tuple[str, str, str, str, str]:
    url = _origin(os.getenv("ODOO_URL", ""))
    db, key, user = (os.getenv(n, "").strip() for n in ("ODOO_DB_NAME", "ODOO_API_KEY", "ODOO_API_USER"))
    transport = os.getenv("ODOO_API_TRANSPORT", "json2").strip().lower()
    if transport not in ("json2", "xmlrpc"):
        raise OdooUnavailable(f"ODOO_API_TRANSPORT must be 'json2' or 'xmlrpc', got {transport!r}")
    if not (url and db and key) or (transport == "xmlrpc" and not user):
        raise OdooUnavailable("Odoo API is not configured: set ODOO_URL, ODOO_DB_NAME and ODOO_API_KEY "
                              "(and ODOO_API_USER for the xmlrpc transport)")
    return url, db, key, user, transport


def _safe(e, key: str) -> str:
    """Error text for logs and API answers: never the API key, never a long server traceback."""
    return " ".join(str(getattr(e, "faultString", e)).replace(key, "***").split())[:200]


# ---------- transport: JSON-2 ----------
def _http_post(url: str, headers: dict, body: bytes) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _detail(text: str, key: str) -> str:
    try:
        message = json.loads(text).get("message") or text
    except (ValueError, AttributeError):
        message = text
    return _safe(message, key)


class _Json2:
    def __init__(self, url: str, db: str, key: str):
        self.url, self.db, self.key = url, db, key

    def call(self, model: str, method: str, params: dict):
        headers = {"Authorization": f"bearer {self.key}", "Content-Type": "application/json; charset=utf-8",
                   "X-Odoo-Database": self.db}
        try:
            status, text = _http_post(f"{self.url}/json/2/{model}/{method}", headers, json.dumps(params).encode())
        except OSError as e:
            raise OdooUnavailable(f"cannot reach the Odoo API: {_safe(e, self.key)}") from e
        if status == 401:
            raise OdooUnavailable("Odoo API login failed (HTTP 401): check ODOO_DB_NAME and ODOO_API_KEY, "
                                  "and that the key may use the external API")
        if status == 403:
            raise OdooUnavailable(f"Odoo API access denied ({model}.{method}): {_detail(text, self.key)} "
                                  "The key's user needs access rights to this data (for invoices: Accounting / Invoicing).")
        if status >= 400:
            raise OdooUnavailable(f"Odoo API request failed ({model}.{method}, HTTP {status}): {_detail(text, self.key)}")
        try:
            return json.loads(text)
        except ValueError as e:
            raise OdooUnavailable("Odoo API answered with something that is not JSON") from e


# ---------- transport: XML-RPC (legacy) ----------
class _HttpTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = TIMEOUT
        return conn


class _HttpsTransport(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = TIMEOUT
        return conn


def _proxy(url: str, path: str):
    transport = _HttpsTransport() if url.startswith("https") else _HttpTransport()
    return xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/{path}", transport=transport, allow_none=True)


class _XmlRpc:
    def __init__(self, url: str, db: str, user: str, key: str):
        self.url, self.db, self.key = url, db, key
        try:
            uid = _proxy(url, "common").authenticate(db, user, key, {})
        except (xmlrpc.client.Error, OSError) as e:
            raise OdooUnavailable(f"cannot reach the Odoo API: {_safe(e, key)}") from e
        if not uid:
            raise OdooUnavailable("Odoo API login failed: check ODOO_DB_NAME, ODOO_API_USER and ODOO_API_KEY")
        self.uid = uid
        self.models = _proxy(url, "object")

    def call(self, model: str, method: str, params: dict):
        params = dict(params)
        first = params.pop(FIRST_ARG[method])
        try:
            return self.models.execute_kw(self.db, self.uid, self.key, model, method, [first], params)
        except (xmlrpc.client.Error, OSError) as e:
            raise OdooUnavailable(f"Odoo API request failed ({model}.{method}): {_safe(e, self.key)}") from e


# ---------- client ----------
class _Client:
    def __init__(self):
        url, db, key, user, transport = _settings()
        self.backend = _Json2(url, db, key) if transport == "json2" else _XmlRpc(url, db, user, key)

    def call(self, model: str, method: str, **params):
        if method not in READ_METHODS:
            raise ValueError(f"refusing to call non-read Odoo method {method!r}")
        return self.backend.call(model, method, params)

    def search_read(self, model: str, domain: list, fields: list, order: str) -> list[dict]:
        rows, offset = [], 0
        while True:
            page = self.call(model, "search_read", domain=domain, fields=fields, order=order, offset=offset, limit=PAGE)
            rows += page
            if len(page) < PAGE:
                return rows
            offset += PAGE

    def read(self, model: str, ids, fields: list) -> list[dict]:
        ids, out = sorted(set(ids)), []
        for i in range(0, len(ids), PAGE):
            out += self.call(model, "read", ids=ids[i:i + PAGE], fields=fields)
        return out


# ---------- the data the app needs ----------
def _ref(value, record_id) -> str:
    """Odoo returns False for an empty text field; fall back to the record id, as the SQL reader does."""
    return value if isinstance(value, str) and value else str(record_id)


def _partners(client: _Client, ids) -> dict[int, dict]:
    return {p["id"]: p for p in client.read("res.partner", ids, ["ref", "name", "email"])}


def _invoices(only_open: bool) -> list[Invoice]:
    client = _Client()
    domain = [("move_type", "=", "out_invoice"), ("state", "=", "posted")]
    if only_open:
        domain.append(("amount_residual", ">", 0))
    moves = client.search_read("account.move", domain, _MOVE_FIELDS, order="invoice_date_due, id")
    partners = _partners(client, {m["partner_id"][0] for m in moves if m["partner_id"]})
    out, skipped = [], 0
    for m in moves:
        due = m["invoice_date_due"] or m["invoice_date"]
        if not m["partner_id"] or not due:
            skipped += 1
            continue
        p = partners[m["partner_id"][0]]
        out.append(Invoice(
            invoice_id=_ref(m["ref"], m["id"]), customer_id=_ref(p["ref"], p["id"]), display_name=p["name"],
            due_date=due, invoice_amount=round(m["amount_total"]), remaining_amount=round(m["amount_residual"]),
            dispute_status="disputed" if "[DISPUTE]" in str(m["narration"] or "") else "none",
            contact_email=p["email"] or None,
        ))
    if skipped:
        log.warning("skipped %d invoice(s) without a customer or a due date", skipped)
    return out


def open_invoices() -> list[Invoice]:
    return _invoices(only_open=True)


def all_invoices() -> list[Invoice]:
    """Open and fully paid invoices. Prediction history needs the paid ones (due date, amount)."""
    return _invoices(only_open=False)


def payment_history() -> list[Payment]:
    client = _Client()
    recs = client.search_read(
        "account.partial.reconcile",
        [("debit_move_id.move_id.move_type", "=", "out_invoice"), ("debit_move_id.move_id.state", "=", "posted")],
        ["debit_move_id", "amount", "max_date"], order="id")
    lines = client.read("account.move.line", {r["debit_move_id"][0] for r in recs}, ["move_id"])
    move_of_line = {ln["id"]: ln["move_id"][0] for ln in lines}
    moves = {m["id"]: m for m in client.read("account.move", set(move_of_line.values()), ["ref", "partner_id"])}
    partners = _partners(client, {m["partner_id"][0] for m in moves.values() if m["partner_id"]})
    out = []
    for r in recs:
        move = moves.get(move_of_line.get(r["debit_move_id"][0]))
        if not move or not move["partner_id"] or not r["max_date"]:
            continue
        p = partners[move["partner_id"][0]]
        out.append(Payment(payment_id=str(r["id"]), invoice_id=_ref(move["ref"], move["id"]),
                           customer_id=_ref(p["ref"], p["id"]), payment_date=r["max_date"],
                           amount=round(r["amount"])))
    return out
