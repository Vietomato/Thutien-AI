"""Business data read from Odoo: invoices, payments, summary, predictions, forecast.
Staff see everything; a customer sees only the invoices and payments linked to their own Odoo customer id."""
from fastapi import APIRouter, Depends

from . import analytics, odoo_reader
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
    preds = analytics.predict(odoo_reader.open_invoices(), odoo_reader.paid_delays(), as_of)
    return envelope(items=[p.model_dump(mode="json") for p in preds])


@router.get("/forecast", dependencies=[Depends(require_permission("forecast:read"))])
def forecast():
    as_of = as_of_date()
    invoices = odoo_reader.open_invoices()
    preds = analytics.predict(invoices, odoo_reader.paid_delays(), as_of)
    weeks = analytics.forecast(invoices, preds, odoo_reader.supplier_bills(), as_of)
    return envelope(weeks=[w.model_dump(mode="json") for w in weeks],
                    risky_weeks=sum(1 for w in weeks if w.gap_p75 > 0))
