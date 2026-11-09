"""F3 priority list for accounting staff."""
from fastapi import APIRouter, Depends

from . import analytics, drafts, odoo_reader
from .auth import require_permission
from .config import as_of_date, data_source
from .f3_priority import rank_priority

router = APIRouter(prefix="/api/f3", tags=["F3 priority"])


@router.get("/priority", dependencies=[Depends(require_permission("invoice:read_all"))])
def priority():
    as_of = as_of_date()
    invoices = odoo_reader.open_invoices()
    delays = odoo_reader.paid_delays(as_of)
    predictions = analytics.predict(invoices, delays, as_of)
    items = rank_priority(
        invoices,
        delays,
        as_of_date=as_of,
        predictions=predictions,
        active_draft_invoice_ids=drafts.pending_invoice_ids(),
    )
    return {"source": data_source(), "as_of_date": as_of.isoformat(), "items": items}
