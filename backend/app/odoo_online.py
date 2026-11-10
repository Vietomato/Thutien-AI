"""Read-only Odoo Online JSON-2 adapter (Odoo 19+).

Only ``search_read`` is called. The API key stays on the backend and is never
sent to the browser or included in exception messages.
"""
import json
import os
import threading
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import Invoice, Payment


class OdooOnlineError(Exception):
    pass


_PAGE_SIZE = 200
_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_LOCK = threading.RLock()


def _settings() -> tuple[str, str, str]:
    url = os.getenv("ODOO_ONLINE_URL", "").strip().rstrip("/")
    key = os.getenv("ODOO_ONLINE_API_KEY", "").strip()
    database = os.getenv("ODOO_ONLINE_DB", "").strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise OdooOnlineError("ODOO_ONLINE_URL must be an HTTPS origin, without a path")
    if not key:
        raise OdooOnlineError("ODOO_ONLINE_API_KEY is not set")
    return url, key, database


def _call(model: str, method: str, **params):
    url, key, database = _settings()
    headers = {
        "Authorization": f"bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": "ThuTienAI-Odoo-Reader/1.0",
    }
    if database:
        headers["X-Odoo-Database"] = database
    request = Request(f"{url}/json/2/{model}/{method}",
                      data=json.dumps(params).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        # Odoo may echo request details in its error body. Never forward that body.
        if exc.code in (401, 403):
            raise OdooOnlineError(f"Odoo Online denied API access (HTTP {exc.code}); check plan, key and user rights") from None
        raise OdooOnlineError(f"Odoo Online API failed (HTTP {exc.code})") from None
    except (URLError, TimeoutError, ValueError) as exc:
        raise OdooOnlineError("Odoo Online API is unavailable or returned invalid JSON") from None


def _search_read(model: str, domain: list, fields: list[str]) -> list[dict]:
    rows: list[dict] = []
    for page in range(100):
        batch = _call(model, "search_read", domain=domain, fields=fields,
                      offset=page * _PAGE_SIZE, limit=_PAGE_SIZE, order="id")
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise OdooOnlineError("Odoo Online returned an unexpected search_read response")
        rows.extend(batch)
        if len(batch) < _PAGE_SIZE:
            return rows
    raise OdooOnlineError("Odoo Online result exceeded the 20,000-record safety limit")


def _read_ids(model: str, ids: set[int], fields: list[str]) -> dict[int, dict]:
    ordered = sorted(ids)
    rows: dict[int, dict] = {}
    for start in range(0, len(ordered), _PAGE_SIZE):
        for item in _search_read(model, [["id", "in", ordered[start:start + _PAGE_SIZE]]], fields):
            rows[int(item["id"])] = item
    return rows


def _related_id(value) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _rounded(value) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _invoice_id(move: dict) -> str:
    return str(move.get("name") if move.get("name") not in (None, False, "/") else
               move.get("ref") or move["id"])


def _partners(moves: list[dict]) -> dict[int, dict]:
    return _read_ids("res.partner", {pid for m in moves if (pid := _related_id(m.get("partner_id")))},
                     ["id", "name", "ref", "email"])


def _currencies(moves: list[dict]) -> dict[int, str]:
    records = _read_ids("res.currency", {cid for m in moves if (cid := _related_id(m.get("currency_id")))},
                        ["id", "name"])
    return {cid: str(row.get("name") or "") for cid, row in records.items()}


def _is_vnd(move: dict, currencies: dict[int, str]) -> bool:
    return currencies.get(_related_id(move.get("currency_id"))) == "VND"


def _to_invoice(move: dict, partners: dict[int, dict]) -> Invoice | None:
    partner_id = _related_id(move.get("partner_id"))
    partner = partners.get(partner_id or -1, {})
    due = move.get("invoice_date_due")
    if not partner_id or not due:
        return None
    version = move.get("write_date") or move.get("create_date")
    if not version:
        raise OdooOnlineError("Odoo Online invoice has no version timestamp")
    name = partner.get("name") or (move["partner_id"][1] if isinstance(move["partner_id"], list) else "")
    email = partner.get("email") or None
    narration = str(move.get("narration") or "")
    dispute_field = os.getenv("ODOO_ONLINE_DISPUTE_FIELD", "").strip()
    disputed = "[DISPUTE]" in narration
    if dispute_field:
        value = move.get(dispute_field)
        disputed = disputed or (value not in (None, False, "", "none", "resolved", "no"))
    return Invoice(invoice_id=_invoice_id(move), customer_id=str(partner.get("ref") or partner_id),
                   display_name=str(name), due_date=date.fromisoformat(str(due)),
                   invoice_amount=_rounded(move["amount_total"]),
                   remaining_amount=_rounded(move["amount_residual"]),
                   dispute_status="disputed" if disputed else "none", contact_email=email,
                   source_version=str(version))


def _cached(name: str, loader, ttl: int = 5):
    url, key, database = _settings()
    # Cache only within one configured source/key; the API key itself is not a cache key.
    cache_key = f"{name}:{url}:{database}:{hash(key)}"
    with _CACHE_LOCK:
        hit = _CACHE.get(cache_key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        value = loader()
        _CACHE[cache_key] = (time.monotonic() + ttl, value)
        return value


_OPEN_DOMAIN = [["move_type", "=", "out_invoice"], ["state", "=", "posted"],
                ["amount_residual", ">", 0]]
_MOVE_FIELDS = ["id", "name", "ref", "partner_id", "invoice_date_due", "amount_total",
                "amount_residual", "currency_id", "narration", "write_date", "create_date"]


def _load_open_invoices() -> list[Invoice]:
    fields = _MOVE_FIELDS + ([os.environ["ODOO_ONLINE_DISPUTE_FIELD"]] if os.getenv("ODOO_ONLINE_DISPUTE_FIELD") else [])
    moves = _search_read("account.move", _OPEN_DOMAIN, fields)
    partners, currencies = _partners(moves), _currencies(moves)
    return [inv for move in moves if _is_vnd(move, currencies)
            if (inv := _to_invoice(move, partners)) is not None]


def open_invoices(customer_id: str | None = None) -> list[Invoice]:
    items = _cached("open_invoices", _load_open_invoices)
    return [i for i in items if i.customer_id == customer_id] if customer_id is not None else list(items)


def open_invoice(invoice_id: str) -> Invoice | None:
    # Always reread for T19 approval checks; the list cache must not hide a changed debt.
    for field in ("name", "ref"):
        moves = _search_read("account.move", _OPEN_DOMAIN + [[field, "=", invoice_id]],
                             _MOVE_FIELDS + ([os.environ["ODOO_ONLINE_DISPUTE_FIELD"]] if os.getenv("ODOO_ONLINE_DISPUTE_FIELD") else []))
        if moves:
            partners, currencies = _partners(moves), _currencies(moves)
            return _to_invoice(moves[0], partners) if _is_vnd(moves[0], currencies) else None
    return None


def _load_payments() -> list[tuple[Payment, date | None, bool]]:
    partials = _search_read("account.partial.reconcile",
                            [["debit_move_id.move_id.move_type", "=", "out_invoice"],
                             ["debit_move_id.move_id.state", "=", "posted"]],
                            ["id", "debit_move_id", "max_date", "amount"])
    lines = _read_ids("account.move.line",
                      {lid for p in partials if (lid := _related_id(p.get("debit_move_id")))},
                      ["id", "move_id"])
    moves = _read_ids("account.move",
                      {mid for line in lines.values() if (mid := _related_id(line.get("move_id")))},
                      ["id", "name", "ref", "partner_id", "invoice_date_due", "amount_residual", "currency_id"])
    partners, currencies = _partners(list(moves.values())), _currencies(list(moves.values()))
    result = []
    for partial in partials:
        line = lines.get(_related_id(partial.get("debit_move_id")) or -1)
        move = moves.get(_related_id(line.get("move_id")) or -1) if line else None
        if not move or not _is_vnd(move, currencies) or not partial.get("max_date"):
            continue
        partner_id = _related_id(move.get("partner_id"))
        if not partner_id:
            continue
        partner = partners.get(partner_id, {})
        payment = Payment(payment_id=str(partial["id"]), invoice_id=_invoice_id(move),
                          customer_id=str(partner.get("ref") or partner_id),
                          payment_date=date.fromisoformat(str(partial["max_date"])),
                          amount=_rounded(partial["amount"]))
        due = date.fromisoformat(str(move["invoice_date_due"])) if move.get("invoice_date_due") else None
        result.append((payment, due, _rounded(move.get("amount_residual") or 0) == 0))
    return result


def payment_history(customer_id: str | None = None) -> list[Payment]:
    rows = _cached("payments", _load_payments, ttl=30)
    return [p for p, _, _ in rows if customer_id is None or p.customer_id == customer_id]


def paid_delays(as_of_date: date | None = None) -> list[tuple[str, int]]:
    latest: dict[str, tuple[str, date, date]] = {}
    for payment, due, fully_paid in _cached("payments", _load_payments, ttl=30):
        if fully_paid and due:
            previous = latest.get(payment.invoice_id)
            if previous is None or payment.payment_date > previous[2]:
                latest[payment.invoice_id] = (payment.customer_id, due, payment.payment_date)
    return [(customer_id, (last_payment - due).days) for customer_id, due, last_payment in latest.values()
            if as_of_date is None or last_payment <= as_of_date]


def _load_bills() -> list[tuple[date, int]]:
    moves = _search_read("account.move", [["move_type", "=", "in_invoice"], ["state", "=", "posted"],
                                          ["amount_residual", ">", 0]],
                         ["id", "invoice_date_due", "amount_residual", "currency_id"])
    currencies = _currencies(moves)
    return [(date.fromisoformat(str(m["invoice_date_due"])), _rounded(m["amount_residual"]))
            for m in moves if m.get("invoice_date_due") and _is_vnd(m, currencies)]


def supplier_bills() -> list[tuple[date, int]]:
    return list(_cached("bills", _load_bills))


def _load_customers() -> list[dict]:
    moves = _search_read("account.move", [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
                         ["id", "partner_id"])
    partners = _partners(moves)
    return sorted(({"customer_id": str(p.get("ref") or pid), "name": str(p.get("name") or "")}
                   for pid, p in partners.items()), key=lambda item: item["customer_id"])


def customers() -> list[dict]:
    return list(_cached("customers", _load_customers, ttl=60))
