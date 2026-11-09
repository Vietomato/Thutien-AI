"""T08: baseline payment-date prediction. Pure functions: no database, no network, no clock.

Method (contract C05)
  delay = completion date - due date, in days (negative = paid early).
  History = invoices fully paid on or before as_of. A payment dated after as_of is never used,
  so the result cannot see the future.
  Per open invoice we take P25/P50/P75 of the delays:
    - customer has >= MIN_HISTORY paid invoices -> the customer's own delays   (customer_median)
    - otherwise, any paid invoice exists         -> every customer's delays    (global_median, low_history)
    - no paid invoice at all                     -> delay 0                    (no_history, low_history)
  Predicted date = due date + delay. If that falls before as_of the date is clamped to as_of and
  overdue_adjusted is set. The clamp is a demo rule, not a calibrated prediction for overdue debt.

P25/P50/P75 are three quantiles of one series, not a confidence interval."""
from collections import defaultdict
from datetime import date, timedelta
from math import floor

from .contracts import Invoice, Payment, Prediction

MIN_HISTORY = 5


def percentile(values: list[int], q: float) -> float:
    """Linear-interpolated percentile (the 'inclusive' method). q is in [0, 1]."""
    if not values:
        raise ValueError("percentile of an empty list")
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def delay_quantiles(delays: list[int]) -> tuple[int, int, int]:
    """(P25, P50, P75) rounded half up to whole days. Always non-decreasing."""
    return tuple(floor(percentile(delays, q) + 0.5) for q in (0.25, 0.5, 0.75))  # type: ignore[return-value]


def paid_delays(invoices: list[Invoice], payments: list[Payment], as_of: date) -> dict[str, list[int]]:
    """Delay in days of every invoice fully paid by as_of, grouped by customer.

    `invoices` must include already-paid invoices (their due date and amount are needed).
    An invoice counts as paid on the day its running total of payments reaches invoice_amount,
    counting only payments dated on or before as_of."""
    known: dict[str, list[Payment]] = defaultdict(list)
    for p in payments:
        if p.payment_date <= as_of:
            known[p.invoice_id].append(p)
    out: dict[str, list[int]] = defaultdict(list)
    for inv in invoices:
        total = 0
        for p in sorted(known.get(inv.invoice_id, []), key=lambda x: x.payment_date):
            total += p.amount
            if total >= inv.invoice_amount:
                out[inv.customer_id].append((p.payment_date - inv.due_date).days)
                break
    return out


def predict_invoice(inv: Invoice, as_of: date, customer_delays: list[int], all_delays: list[int]) -> Prediction:
    if len(customer_delays) >= MIN_HISTORY:
        pool, method, low = customer_delays, "customer_median", False
    elif all_delays:
        pool, method, low = all_delays, "global_median", True
    else:
        pool, method, low = [0], "no_history", True
    q25, q50, q75 = delay_quantiles(pool)
    dates = [inv.due_date + timedelta(days=d) for d in (q25, q50, q75)]
    adjusted = any(d < as_of for d in dates)
    p25, p50, p75 = (max(d, as_of) for d in dates)
    return Prediction(
        invoice_id=inv.invoice_id, as_of_date=as_of,
        predicted_date_p25=p25, predicted_date_p50=p50, predicted_date_p75=p75,
        history_count=len(customer_delays), method=method, low_history=low, overdue_adjusted=adjusted,
    )


def predict(open_invoices: list[Invoice], history_invoices: list[Invoice], payments: list[Payment],
            as_of: date) -> list[Prediction]:
    """One prediction per open invoice (remaining_amount > 0), in the order given.

    history_invoices: every invoice that may carry history, paid ones included."""
    by_customer = paid_delays(history_invoices, payments, as_of)
    everyone = [d for ds in by_customer.values() for d in ds]
    return [predict_invoice(i, as_of, by_customer.get(i.customer_id, []), everyone)
            for i in open_invoices if i.remaining_amount > 0]
