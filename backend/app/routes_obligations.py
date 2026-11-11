"""Expected outgoings entered by the accountant. They are added to the Odoo supplier bills in the F4 forecast."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
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
