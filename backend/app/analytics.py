"""Payment prediction, 12-week cash forecast and summary. Pure functions: no database, no network.
Inputs come from odoo_reader; every number here is computed from real invoices and payments.

Prediction method
  For each open invoice we look at how many days late (after the due date) the customer paid their
  earlier invoices. P25/P50/P75 of those delays give three payment dates.
  - Fewer than MIN_HISTORY paid invoices for the customer: use all customers' delays (low_history).
  - No history at all: assume payment on max(due date, as_of date) (method 'no_history').
  - Overdue invoice: only delays at least as long as the current overdue count are plausible, so we keep
    those. If every past delay was shorter than the current overdue, the invoice is already later than
    anything seen; we then count the typical delay from the as_of date (overdue_adjusted).
  - Disputed invoices get no prediction (they are not chased automatically either)."""
from collections import defaultdict
from datetime import date, timedelta

from .contracts import Invoice, Prediction, Week

MIN_HISTORY = 3
WEEKS = 12


def percentile(sorted_values: list[int], q: float) -> float:
    """Linear-interpolated percentile of an ascending list. q in [0, 1]."""
    if not sorted_values:
        raise ValueError("empty list")
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _quantiles(values: list[int]) -> tuple[int, int, int]:
    s = sorted(values)
    return tuple(round(percentile(s, q)) for q in (0.25, 0.5, 0.75))  # type: ignore[return-value]


def group_delays(delays: list[tuple[str, int]]) -> dict[str, list[int]]:
    by_customer: dict[str, list[int]] = defaultdict(list)
    for customer_id, days in delays:
        by_customer[customer_id].append(days)
    return by_customer


def predict_invoice(inv: Invoice, as_of: date, customer_delays: list[int], all_delays: list[int]) -> Prediction | None:
    if inv.dispute_status == "disputed":
        return None
    overdue = (as_of - inv.due_date).days
    if len(customer_delays) >= MIN_HISTORY:
        pool, method, low = customer_delays, "customer_median", False
    elif len(all_delays) >= MIN_HISTORY:
        pool, method, low = all_delays, "global_median", True
    else:
        day = max(inv.due_date, as_of)
        return Prediction(invoice_id=inv.invoice_id, as_of_date=as_of, predicted_date_p25=day,
                          predicted_date_p50=day, predicted_date_p75=day, history_count=len(customer_delays),
                          method="no_history", low_history=True, overdue_adjusted=overdue > 0)
    plausible = [d for d in pool if d >= overdue]
    adjusted = not plausible
    if plausible:
        dates = [inv.due_date + timedelta(days=o) for o in _quantiles(plausible)]
    else:
        dates = [as_of + timedelta(days=max(1, o)) for o in _quantiles(pool)]
    dates = [max(d, as_of) for d in dates]
    return Prediction(invoice_id=inv.invoice_id, as_of_date=as_of, predicted_date_p25=dates[0],
                      predicted_date_p50=dates[1], predicted_date_p75=dates[2], history_count=len(customer_delays),
                      method=method, low_history=low, overdue_adjusted=adjusted)


def predict(invoices: list[Invoice], delays: list[tuple[str, int]], as_of: date) -> list[Prediction]:
    by_customer = group_delays(delays)
    everyone = [d for _, d in delays]
    out = []
    for inv in invoices:
        p = predict_invoice(inv, as_of, by_customer.get(inv.customer_id, []), everyone)
        if p:
            out.append(p)
    return out


def _week_index(day: date, as_of: date) -> int:
    return (day - as_of).days // 7


def forecast(invoices: list[Invoice], predictions: list[Prediction], bills: list[tuple[date, int]],
             as_of: date, weeks: int = WEEKS) -> list[Week]:
    """Per week: expected receipts under the early (P25), middle (P50) and late (P75) scenario, and the
    money that must go out (supplier bills due that week; bills already overdue count in week 1)."""
    amount = {i.invoice_id: i.remaining_amount for i in invoices}
    receipts = {"p25": [0] * weeks, "p50": [0] * weeks, "p75": [0] * weeks}
    for p in predictions:
        amt = amount.get(p.invoice_id, 0)
        for key, day in (("p25", p.predicted_date_p25), ("p50", p.predicted_date_p50), ("p75", p.predicted_date_p75)):
            idx = _week_index(day, as_of)
            if 0 <= idx < weeks:
                receipts[key][idx] += amt
    obligations = [0] * weeks
    for due, amt in bills:
        idx = max(0, _week_index(due, as_of))
        if idx < weeks:
            obligations[idx] += amt
    return [
        Week(week_start=as_of + timedelta(days=7 * i),
             receipt_p25=receipts["p25"][i], receipt_p50=receipts["p50"][i], receipt_p75=receipts["p75"][i],
             obligations=obligations[i], gap_p75=max(obligations[i] - receipts["p75"][i], 0))
        for i in range(weeks)
    ]


def summarize(invoices: list[Invoice], as_of: date) -> dict:
    total = overdue = disputed = 0
    overdue_n = disputed_n = 0
    days = []
    for inv in invoices:
        total += inv.remaining_amount
        late = (as_of - inv.due_date).days
        if late > 0:
            overdue += inv.remaining_amount
            overdue_n += 1
            days.append(late)
        if inv.dispute_status == "disputed":
            disputed += inv.remaining_amount
            disputed_n += 1
    return {
        "total_remaining": total, "open_count": len(invoices),
        "overdue_amount": overdue, "overdue_count": overdue_n,
        "min_overdue_days": min(days) if days else 0, "max_overdue_days": max(days) if days else 0,
        "disputed_amount": disputed, "disputed_count": disputed_n,
    }
