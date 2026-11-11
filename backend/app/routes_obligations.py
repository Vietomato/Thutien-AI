"""Expected outgoings entered by the accountant. They are added to the Odoo supplier bills in the F4 forecast."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import obligations
from .audit import append_audit
from .auth import require_permission
from .routes_data import envelope

router = APIRouter(prefix="/api", tags=["forecast"])


class ObligationIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: int = Field(gt=0)
    currency: Literal["VND"] = "VND"
    due_date: date


@router.get("/obligations", dependencies=[Depends(require_permission("forecast:read"))])
def list_obligations():
    return envelope(origin="manual", items=obligations.list_all())


@router.post("/obligations", status_code=201)
def add_obligation(body: ObligationIn, user: dict = Depends(require_permission("obligation:write"))):
    record = obligations.create(body.description, body.amount, body.due_date, user["id"])
    append_audit(user["username"], "obligation_created", f"obligation:{record['id']}",
                 {"amount": record["amount"], "due_date": record["due_date"]})
    return record


@router.patch("/obligations/{obligation_id}")
def edit_obligation(obligation_id: int, body: ObligationIn,
                    user: dict = Depends(require_permission("obligation:write"))):
    record = obligations.update(obligation_id, body.description, body.amount, body.due_date)
    if record is None:
        raise HTTPException(404, "obligation not found")
    append_audit(user["username"], "obligation_updated", f"obligation:{obligation_id}",
                 {"amount": record["amount"], "due_date": record["due_date"]})
    return record


@router.delete("/obligations/{obligation_id}")
def remove_obligation(obligation_id: int, user: dict = Depends(require_permission("obligation:write"))):
    record = obligations.delete(obligation_id)
    if record is None:
        raise HTTPException(404, "obligation not found")
    append_audit(user["username"], "obligation_deleted", f"obligation:{obligation_id}", record)
    return {"deleted": True, "id": obligation_id}
