"""Business data read from Odoo: invoices, payments, summary, predictions, forecast.
Staff see everything; a customer sees only the invoices and payments linked to their own Odoo customer id."""
from datetime import date

from fastapi import APIRouter, Depends

from . import analytics, obligations, odoo_reader
from .auth import require_any_permission, require_permission
from .config import as_of_date, data_source
from .permissions import has_permission

router = APIRouter(prefix="/api", tags=["data"])


def envelope(**extra) -> dict:
    return {"source": data_source(), "as_of_date": as_of_date().isoformat(), **extra}


def customer_scope(user: dict, all_perm: str) -> tuple[bool, str | None]:
    """Returns (has_data_access, customer_filter). customer_filter None means no filter (staff)."""
    if has_permission(user["role"], all_perm):
        return True, None
    return bool(user["customer_id"]), user["customer_id"]


@router.get("/invoices/open")
def invoices_open(user: dict = Depends(require_any_permission("invoice:read_all", "invoice:read_own"))):
    ok, cust = customer_scope(user, "invoice:read_all")
    items = odoo_reader.open_invoices(cust) if ok else []
    return envelope(scope="all" if cust is None else "own", items=[i.model_dump(mode="json") for i in items])


@router.get("/payments/history")
def payments_history(user: dict = Depends(require_any_permission("payment:read_all", "payment:read_own"))):
    ok, cust = customer_scope(user, "payment:read_all")
    items = odoo_reader.payment_history(cust) if ok else []
    return envelope(scope="all" if cust is None else "own", items=[p.model_dump(mode="json") for p in items])


@router.get("/summary")
def summary(user: dict = Depends(require_any_permission("summary:read_all", "summary:read_own"))):
    ok, cust = customer_scope(user, "summary:read_all")
    invoices = odoo_reader.open_invoices(cust) if ok else []
    return envelope(scope="all" if cust is None else "own", **analytics.summarize(invoices, as_of_date()))


@router.get("/predictions", dependencies=[Depends(require_permission("prediction:read"))])
def predictions():
    as_of = as_of_date()
    preds = analytics.predict(odoo_reader.open_invoices(), odoo_reader.paid_delays(as_of), as_of)
    return envelope(items=[p.model_dump(mode="json") for p in preds])


@router.get("/forecast", dependencies=[Depends(require_permission("forecast:read"))])
def forecast():
    """Receipts per week (early / usual / late scenario, plus the probability-weighted expected figure) against outgoings: supplier bills read from Odoo plus the
    expected outgoings the accountant typed in. Money beyond the last week is reported, not dropped."""
    as_of = as_of_date()
    invoices = odoo_reader.open_invoices()
    delays = odoo_reader.paid_delays(as_of)
    preds = analytics.predict(invoices, delays, as_of)
    odoo_bills = odoo_reader.supplier_bills()
    manual = obligations.list_all()
    bills = odoo_bills + [(date.fromisoformat(o["due_date"]), o["amount"]) for o in manual]
    weeks = analytics.forecast(invoices, preds, bills, as_of, expected=analytics.expected_receipts(invoices, delays, as_of))
    return envelope(
        weeks=[w.model_dump(mode="json") for w in weeks],
        risky_weeks=sum(1 for w in weeks if w.gap_p75 > 0),
        alerts=[{"week_start": w.week_start.isoformat(), "receipt_p75": w.receipt_p75,
                 "obligations": w.obligations, "gap_p75": w.gap_p75} for w in weeks if w.gap_p75 > 0],
        week_invoices=analytics.week_contributions(invoices, delays, as_of),
        receipts_out_of_horizon=analytics.beyond_horizon(invoices, preds, as_of),
        obligations_out_of_horizon=analytics.bills_beyond_horizon(bills, as_of),
        obligations_sources={"odoo_supplier_bills": sum(a for _, a in odoo_bills),
                             "manual": sum(o["amount"] for o in manual), "manual_count": len(manual)},
    )
