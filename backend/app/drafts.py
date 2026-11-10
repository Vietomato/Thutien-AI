"""Reminder drafts: deterministic fallback text and application database storage.

The text is built from real invoice fields by a fixed template; numbers are never free-typed.
Approving a draft only records the decision. This app has no email sender, so nothing is delivered."""
from datetime import date

from psycopg import errors as pg_errors

from .audit import append_audit
from .contracts import Invoice
from .db import connect

_COLUMNS = (
    "d.id, d.invoice_id, d.customer_id, d.customer_name, d.contact_email, d.amount, d.due_date, d.overdue_days, "
    "d.source_version, d.subject, d.body, d.generation_source, d.status, d.created_by, cu.username AS created_by_username, d.created_at, "
    "d.decided_by, du.username AS decided_by_username, d.decided_at, d.decision_note"
)
_FROM = ("FROM reminder_drafts d JOIN users cu ON cu.id = d.created_by "
         "LEFT JOIN users du ON du.id = d.decided_by")


class DraftExists(Exception):
    pass


def vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def compose(inv: Invoice, pay_by: date) -> tuple[str, str]:
    subject = f"Nhắc thanh toán hóa đơn {inv.invoice_id}"
    body = "\n\n".join([
        f"Kính gửi {inv.display_name},",
        f"Theo hồ sơ của chúng tôi, hóa đơn {inv.invoice_id} trị giá {vnd(inv.remaining_amount)} VND đã đến hạn "
        f"từ ngày {dmy(inv.due_date)} và hiện chưa được thanh toán.",
        f"Mong quý khách sắp xếp thanh toán trước ngày {dmy(pay_by)}. "
        "Nếu quý khách đã thanh toán, xin vui lòng bỏ qua thư này.",
        "Trân trọng,\nPhòng Kế toán",
    ])
    return subject, body


def _row(r: dict) -> dict:
    r = dict(r)
    for k in ("created_at", "decided_at", "due_date"):
        if r.get(k):
            r[k] = r[k].isoformat()
    return r


def create(inv: Invoice, overdue_days: int, subject: str, body: str, created_by: int,
           generation_source: str = "template_fallback") -> dict:
    try:
        with connect() as conn:
            new_id = conn.execute(
                "INSERT INTO reminder_drafts (invoice_id, customer_id, customer_name, contact_email, amount, due_date, "
                "overdue_days, source_version, subject, body, created_by, generation_source) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (inv.invoice_id, inv.customer_id, inv.display_name, inv.contact_email, inv.remaining_amount,
                 inv.due_date, overdue_days, inv.source_version, subject, body, created_by, generation_source)).fetchone()["id"]
    except pg_errors.UniqueViolation:
        raise DraftExists(inv.invoice_id)
    return get(new_id)  # type: ignore[return-value]


def get(draft_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(f"SELECT {_COLUMNS} {_FROM} WHERE d.id = %s", (draft_id,)).fetchone()
    return _row(row) if row else None


def list_for(creator_ids: list[int], status: str | None = None) -> list[dict]:
    sql = f"SELECT {_COLUMNS} {_FROM} WHERE d.created_by = ANY(%s)"
    params: list = [creator_ids]
    if status:
        sql += " AND d.status = %s"
        params.append(status)
    sql += " ORDER BY (d.status = 'pending') DESC, d.overdue_days DESC, d.id DESC"
    with connect() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


def pending_invoice_ids() -> set[str]:
    with connect() as conn:
        return {r["invoice_id"] for r in conn.execute(
            "SELECT invoice_id FROM reminder_drafts WHERE status = 'pending'").fetchall()}


def update_text(draft_id: int, subject: str | None, body: str | None) -> dict | None:
    """Edit a draft that is still pending. Returns None when it is not pending."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE reminder_drafts SET subject = COALESCE(%s, subject), body = COALESCE(%s, body) "
            "WHERE id = %s AND status = 'pending' RETURNING id", (subject, body, draft_id)).fetchone()
    return get(row["id"]) if row else None


def decide(draft_id: int, status: str, decided_by: int, actor: str, drafted_by: str,
           note: str | None) -> dict | None:
    """Decide once, with an audit entry in the same transaction."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE reminder_drafts SET status = %s, decided_by = %s, decided_at = now(), decision_note = %s "
            "WHERE id = %s AND status = 'pending' AND created_by <> %s "
            "RETURNING id, invoice_id, created_by", (status, decided_by, note, draft_id, decided_by)).fetchone()
        if row:
            append_audit(actor, "approve_draft" if status == "approved" else "reject_draft",
                         row["invoice_id"], {"draft_id": draft_id, "drafted_by": drafted_by, "note": note},
                         conn=conn)
    return get(row["id"]) if row else None
