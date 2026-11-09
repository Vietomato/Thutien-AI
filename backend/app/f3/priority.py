from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PriorityInvoice:
    invoice_id: str
    customer_id: str
    display_name: str
    due_date: date
    invoice_amount: Decimal
    remaining_amount: Decimal
    currency: str = "VND"
    dispute_status: str | bool | None = None
    contact_email: str | None = None


@dataclass(frozen=True)
class CompletedInvoice:
    """A fully settled invoice with the due/completion dates needed for late-rate history."""

    invoice_id: str
    customer_id: str
    due_date: date
    completed_date: date


def _is_disputed(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return (value or "").strip().lower() in {"active", "disputed", "open", "true", "yes", "1"}


def _late_rates(
    history: Iterable[CompletedInvoice], as_of_date: date
) -> tuple[dict[str, Decimal], Decimal | None]:
    counts: dict[str, list[int]] = {}
    global_counts = [0, 0]
    for item in history:
        if item.completed_date > as_of_date:
            continue
        counts.setdefault(item.customer_id, [0, 0])
        is_late = item.completed_date > item.due_date
        counts[item.customer_id][0] += int(is_late)
        counts[item.customer_id][1] += 1
        global_counts[0] += int(is_late)
        global_counts[1] += 1

    customer_rates = {
        customer_id: Decimal(late) / Decimal(total)
        for customer_id, (late, total) in counts.items()
        if total
    }
    global_rate = (
        Decimal(global_counts[0]) / Decimal(global_counts[1])
        if global_counts[1]
        else None
    )
    return customer_rates, global_rate


def rank_priority(
    invoices: Iterable[PriorityInvoice],
    history: Iterable[CompletedInvoice],
    *,
    as_of_date: date,
    predictions: Mapping[str, Mapping[str, Any]] | None = None,
    active_draft_invoice_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Rank open receivables with the agreed F3 heuristic and explain every hold."""
    customer_rates, global_rate = _late_rates(history, as_of_date)
    predictions = predictions or {}
    active_draft_invoice_ids = active_draft_invoice_ids or set()
    result: list[dict[str, Any]] = []

    for invoice in invoices:
        overdue_days = max((as_of_date - invoice.due_date).days, 0)
        rate_source = "customer_history"
        late_rate = customer_rates.get(invoice.customer_id)
        if late_rate is None:
            late_rate = global_rate
            rate_source = "global_history"
        if late_rate is None:
            late_rate = Decimal("0.5")
            rate_source = "assumed_0.5_no_history"

        score = invoice.remaining_amount * late_rate * overdue_days
        reasons: list[str] = []
        if invoice.remaining_amount <= 0:
            reasons.append("no_remaining_balance")
        if overdue_days <= 0:
            reasons.append("not_overdue")
        if _is_disputed(invoice.dispute_status):
            reasons.append("disputed")
        if not invoice.contact_email:
            reasons.append("missing_contact")
        if invoice.invoice_id in active_draft_invoice_ids:
            reasons.append("active_draft_exists")

        result.append(
            {
                "invoice_id": invoice.invoice_id,
                "customer_id": invoice.customer_id,
                "display_name": invoice.display_name,
                "due_date": invoice.due_date.isoformat(),
                "invoice_amount": invoice.invoice_amount,
                "remaining_amount": invoice.remaining_amount,
                "currency": invoice.currency,
                "days_overdue": overdue_days,
                "late_rate": late_rate,
                "late_rate_source": rate_source,
                "priority_score": score,
                "eligible_for_reminder": not reasons,
                "hold_reasons": reasons,
                "prediction": predictions.get(invoice.invoice_id),
            }
        )

    result.sort(
        key=lambda row: (
            -row["priority_score"],
            -row["remaining_amount"],
            row["invoice_id"],
        )
    )
    for rank, row in enumerate(result, start=1):
        row["rank"] = rank
    return result
