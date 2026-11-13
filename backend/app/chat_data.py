"""One consistent read of everything the assistant may talk about, taken once per question.

The tools of the assistant all work on this snapshot, so two tools in the same answer never disagree because Odoo changed in
between. Nothing here writes anywhere."""
from dataclasses import dataclass, field
from datetime import date

from . import analytics, drafts, obligations, odoo_reader, whatif
from .config import as_of_date, data_source
from .contracts import Invoice, Prediction, Week
from .f3_priority import rank_priority


@dataclass
class Snapshot:
    as_of: date
    source: str
    invoices: list[Invoice]
    delays: list[tuple[str, int]]
    outgoings: list[whatif.Outgoing]
    names: dict[str, str]                      # customer id -> name
    predictions: dict[str, Prediction]         # invoice id -> prediction (no entry for disputed invoices)
    ranked: list[dict]                         # the F3 priority rows (rank, score, holds, prediction)
    weeks: list[Week]                          # the base forecast, with the expected line
    pending_draft_invoices: set[str] = field(default_factory=set)


def build_snapshot(as_of: date, source: str, invoices: list[Invoice], delays: list[tuple[str, int]], bills: list[tuple[date, int]],
                   manual: list[dict], customers: list[dict], pending_draft_invoices: set[str]) -> Snapshot:
    """Pure part of the snapshot: everything is passed in (tests use this directly)."""
    outgoings = whatif.outgoings_from(bills, manual)
    predictions = analytics.predict(invoices, delays, as_of)
    names = {c["customer_id"]: c["name"] for c in customers}
    names.update({i.customer_id: i.display_name for i in invoices})
    return Snapshot(
        as_of=as_of, source=source, invoices=invoices, delays=delays, outgoings=outgoings, names=names,
        predictions={p.invoice_id: p for p in predictions},
        ranked=rank_priority(invoices, delays, as_of_date=as_of, predictions=predictions, active_draft_invoice_ids=pending_draft_invoices),
        weeks=whatif.run_forecast(invoices, delays, outgoings, as_of), pending_draft_invoices=pending_draft_invoices)


def load_snapshot() -> Snapshot:
    as_of = as_of_date()
    return build_snapshot(as_of, data_source(), odoo_reader.open_invoices(), odoo_reader.paid_delays(as_of), odoo_reader.supplier_bills(),
                          obligations.list_all(), odoo_reader.customers(), drafts.pending_invoice_ids())
