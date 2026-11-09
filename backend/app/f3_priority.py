"""F3 invoice ranking and reminder eligibility, computed from read-only Odoo data."""
from decimal import Decimal

from .contracts import Invoice, Prediction


def rank_priority(
    invoices: list[Invoice],
    delays: list[tuple[str, int]],
    *,
    as_of_date,
    predictions: list[Prediction],
    active_draft_invoice_ids: set[str],
) -> list[dict]:
    """Return all open invoices, with ranked score and reasons for held reminders."""
    customer_delays: dict[str, list[int]] = {}
    for customer_id, days_late in delays:
        customer_delays.setdefault(customer_id, []).append(days_late)

    global_total = len(delays)
    global_late = sum(days_late > 0 for _, days_late in delays)
    global_rate = Decimal(global_late) / Decimal(global_total) if global_total else None
    prediction_by_id = {p.invoice_id: p for p in predictions}
    ranked = []

    for invoice in invoices:
        history = customer_delays.get(invoice.customer_id, [])
        if history:
            late_rate = Decimal(sum(days > 0 for days in history)) / Decimal(len(history))
            rate_source = "customer_history"
            history_count = len(history)
        elif global_rate is not None:
            late_rate = global_rate
            rate_source = "global_history"
            history_count = global_total
        else:
            late_rate = Decimal("0.5")
            rate_source = "assumed_0.5_no_history"
            history_count = 0

        days_overdue = max((as_of_date - invoice.due_date).days, 0)
        score = Decimal(invoice.remaining_amount) * late_rate * days_overdue
        holds = []
        if invoice.remaining_amount <= 0:
            holds.append("no_remaining_balance")
        if days_overdue <= 0:
            holds.append("not_overdue")
        if invoice.dispute_status == "disputed":
            holds.append("disputed")
        if not (invoice.contact_email or "").strip():
            holds.append("missing_contact")
        if invoice.invoice_id in active_draft_invoice_ids:
            holds.append("active_draft_exists")

        ranked.append({
            **invoice.model_dump(mode="json"),
            "days_overdue": days_overdue,
            "late_rate": str(late_rate),
            "late_rate_source": rate_source,
            "history_count": history_count,
            "priority_score": str(score),
            "eligible_for_reminder": not holds,
            "hold_reasons": holds,
            "prediction": prediction_by_id[invoice.invoice_id].model_dump(mode="json")
            if invoice.invoice_id in prediction_by_id else None,
        })

    ranked.sort(key=lambda row: (-Decimal(row["priority_score"]), -row["remaining_amount"], row["invoice_id"]))
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked
