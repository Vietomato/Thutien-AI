"""F4 API: weekly receipts forecast (three scenarios), expected outgoings entered by hand, shortfall alerts."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from . import forecast as forecast_engine, prediction
from .audit import append_audit
from .auth import require_roles
from .config import as_of_date, data_source
from .forecast import Obligation
from .obligations import ObligationRecord, PostgresObligations
from .sources import load_invoices_and_payments

router = APIRouter(prefix="/api/f4")
f4_roles = require_roles("accountant", "manager")


def obligation_repo() -> PostgresObligations:
    return PostgresObligations()


class ObligationIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount: int = Field(gt=0)
    currency: Literal["VND"] = "VND"
    due_date: date


@router.post("/obligations", status_code=201)
def add_obligation(body: ObligationIn, user: dict = Depends(f4_roles), repo=Depends(obligation_repo)):
    record = repo.add(Obligation(description=body.description, amount=body.amount, due_date=body.due_date),
                      created_by=user["username"])
    append_audit(user["username"], "obligation_created", f"obligation:{record.id}",
                 {"amount": record.amount, "due_date": record.due_date.isoformat()})
    return record.model_dump(mode="json")


@router.get("/obligations", dependencies=[Depends(f4_roles)])
def list_obligations(repo=Depends(obligation_repo)):
    return {"source": "manual", "items": [r.model_dump(mode="json") for r in repo.list_all()]}


@router.get("/forecast", dependencies=[Depends(f4_roles)])
def get_forecast(weeks: int = Query(12, ge=1, le=52), repo=Depends(obligation_repo)):
    as_of = as_of_date()
    invoices, payments = load_invoices_and_payments()
    open_invoices = [i for i in invoices if i.remaining_amount > 0]
    predictions = prediction.predict(open_invoices, invoices, payments, as_of)
    result = forecast_engine.forecast(open_invoices, predictions, list(repo.list_all()), as_of, weeks)
    data = result.model_dump(mode="json")
    data["source"] = data_source()
    data["obligations_source"] = "manual"      # outgoings are typed in by the accountant, not read from Odoo
    data["alerts"] = [
        {"week_start": w.week_start.isoformat(), "receipt_p75": w.receipt_p75,
         "obligations": w.obligations, "gap_p75": w.gap_p75}
        for w in result.weeks if w.gap_p75 > 0
    ]
    return data
