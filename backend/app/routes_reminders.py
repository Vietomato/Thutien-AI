"""Reminder drafts. An accountant creates drafts; the chief accountant approves or rejects them.
Visibility: an accountant sees their own drafts; a chief accountant sees their own and their team's."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import analytics, draft_generation, drafts, odoo_reader, users
from .audit import append_audit, list_draft_history
from .auth import require_any_permission, require_permission
from .config import as_of_date
from .contracts import Invoice
from .permissions import has_permission

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


def _visible_creators(user: dict) -> list[int]:
    ids = [user["id"]]
    if has_permission(user["role"], "draft:read_team"):
        ids += [m["id"] for m in users.team_of(user["id"])]
    return ids


def _checks(d: dict, inv: Invoice | None) -> list[dict]:
    """Re-check the numbers in the draft against Odoo right now."""
    if inv is None:
        return [{"label": "Hóa đơn không còn nợ trên Odoo", "ok": False}]
    amount_ok = inv.remaining_amount == d["amount"]
    due_ok = inv.due_date == date.fromisoformat(d["due_date"])
    customer_ok = inv.customer_id == d["customer_id"] and inv.display_name == d["customer_name"]
    email_ok = inv.contact_email == d["contact_email"]
    version_ok = inv.source_version == d["source_version"]
    clean = inv.dispute_status == "none"
    checks = [
        {"label": f"Số tiền {drafts.vnd(d['amount'])}: " + ("khớp" if amount_ok else "không khớp"), "ok": amount_ok},
        {"label": f"Hạn trả {drafts.dmy(date.fromisoformat(d['due_date']))}: " + ("khớp" if due_ok else "không khớp"),
         "ok": due_ok},
        {"label": "Không tranh chấp" if clean else "Đang tranh chấp", "ok": clean},
    ]


    checks.extend([
        {"label": "Khách hàng: " + ("khớp" if customer_ok else "đã thay đổi"), "ok": customer_ok},
        {"label": "Email liên hệ: " + ("khớp" if email_ok else "đã thay đổi"), "ok": email_ok},
        {"label": "Phiên bản Odoo: " + ("khớp" if version_ok else "đã thay đổi"), "ok": version_ok},
    ])
    return checks


def _with_checks(d: dict, invoices: dict[str, Invoice]) -> dict:
    checks = _checks(d, invoices.get(d["invoice_id"]))
    return {**d, "checks": checks, "checks_ok": all(c["ok"] for c in checks)}


def _visible_or_404(draft_id: int, user: dict) -> dict:
    d = drafts.get(draft_id)
    if d is None or d["created_by"] not in _visible_creators(user):
        raise HTTPException(404, "draft not found")  # same answer whether it exists or is out of scope
    return d


class CreateDraft(BaseModel):
    invoice_id: str


class EditDraft(BaseModel):
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("/candidates", dependencies=[Depends(require_permission("draft:create"))])
def candidates():
    """Overdue invoices that can get a draft now, plus overdue invoices skipped because of a dispute."""
    as_of = as_of_date()
    pending = drafts.pending_invoice_ids()
    ready, disputed = [], []
    for inv in odoo_reader.open_invoices():
        late = (as_of - inv.due_date).days
        if late <= 0:
            continue
        if inv.dispute_status == "disputed":
            disputed.append(inv.invoice_id)
        elif (inv.contact_email or "").strip() and inv.invoice_id not in pending:
            ready.append({**inv.model_dump(mode="json"), "overdue_days": late})
    ready.sort(key=lambda x: -x["overdue_days"])
    return {"as_of_date": as_of.isoformat(), "items": ready, "disputed": disputed}


@router.post("/drafts", status_code=201)
def create_draft(body: CreateDraft, user: dict = Depends(require_permission("draft:create"))):
    as_of = as_of_date()
    inv = odoo_reader.open_invoice(body.invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found or already paid")
    if inv.dispute_status == "disputed":
        raise HTTPException(409, "invoice is disputed, no reminder")
    if not (inv.contact_email or "").strip():
        raise HTTPException(409, "invoice has no contact email")
    late = (as_of - inv.due_date).days
    if late <= 0:
        raise HTTPException(409, "invoice is not overdue")
    delays = odoo_reader.paid_delays(as_of)
    pred = analytics.predict_invoice(
        inv, as_of, analytics.group_delays(delays).get(inv.customer_id, []), [d for _, d in delays])
    subject, text, source = draft_generation.generate(inv, pred.predicted_date_p50 if pred else as_of)
    try:
        d = drafts.create(inv, late, subject, text, user["id"], source)
    except drafts.DraftExists:
        raise HTTPException(409, "a pending draft already exists for this invoice")
    append_audit(user["username"], "create_draft", inv.invoice_id,
                 {"draft_id": d["id"], "generation_source": source})
    return _with_checks(d, {inv.invoice_id: inv})


@router.get("/drafts")
def list_drafts(status: str | None = None,
                user: dict = Depends(require_any_permission("draft:read_own", "draft:read_team"))):
    if status not in (None, "pending", "approved", "rejected"):
        raise HTTPException(422, "invalid status")
    items = drafts.list_for(_visible_creators(user), status)
    invoices = {i.invoice_id: i for i in odoo_reader.open_invoices()} if items else {}
    return {"as_of_date": as_of_date().isoformat(), "items": [_with_checks(d, invoices) for d in items]}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, user: dict = Depends(require_any_permission("draft:read_own", "draft:read_team"))):
    d = _visible_or_404(draft_id, user)
    return _with_checks(d, {i.invoice_id: i for i in [odoo_reader.open_invoice(d["invoice_id"])] if i})


@router.get("/drafts/{draft_id}/history")
def draft_history(draft_id: int, user: dict = Depends(require_any_permission("draft:read_own", "draft:read_team"))):
    _visible_or_404(draft_id, user)
    return {"items": list_draft_history(draft_id)}


@router.patch("/drafts/{draft_id}")
def edit_draft(draft_id: int, body: EditDraft, user: dict = Depends(require_permission("draft:create"))):
    d = _visible_or_404(draft_id, user)
    if d["created_by"] != user["id"]:
        raise HTTPException(403, "only the draft author can edit it")
    if body.subject is None and body.body is None:
        raise HTTPException(422, "nothing to change")
    updated = drafts.update_text(d["id"], body.subject, body.body)
    if updated is None:
        raise HTTPException(409, "only pending drafts can be edited")
    append_audit(user["username"], "edit_draft", d["invoice_id"], {"draft_id": d["id"]})
    return _with_checks(updated, {i.invoice_id: i for i in [odoo_reader.open_invoice(d["invoice_id"])] if i})


def _decide(draft_id: int, status: str, note: str | None, user: dict) -> dict:
    d = _visible_or_404(draft_id, user)
    if d["created_by"] == user["id"]:
        raise HTTPException(403, "cannot decide your own draft")
    if d["status"] != "pending":
        raise HTTPException(409, f"draft is already {d['status']}")
    inv = odoo_reader.open_invoice(d["invoice_id"])
    if status == "approved" and not all(c["ok"] for c in _checks(d, inv)):
        raise HTTPException(409, "invoice data changed in Odoo since this draft was written; reject it and create a new one")
    result = drafts.decide(d["id"], status, user["id"], user["username"], d["created_by_username"], note)
    if result is None:
        raise HTTPException(409, "draft was already decided")
    return _with_checks(result, {i.invoice_id: i for i in [inv] if i})


@router.post("/drafts/{draft_id}/approve")
def approve(draft_id: int, body: Decision | None = None, user: dict = Depends(require_permission("draft:decide"))):
    return _decide(draft_id, "approved", body.note if body else None, user)


@router.post("/drafts/{draft_id}/reject")
def reject(draft_id: int, body: Decision | None = None, user: dict = Depends(require_permission("draft:decide"))):
    return _decide(draft_id, "rejected", body.note if body else None, user)
