"""Payment prediction, 12-week cash forecast and summary. Pure functions: no database, no network.
Inputs come from odoo_reader; every number here is computed from real invoices and payments.

Prediction method
  For each open invoice we look at how many days late (after the due date) the customer paid their
  earlier invoices. P25/P50/P75 of those delays give three payment dates.
  - Fewer than MIN_HISTORY (5) paid invoices for the customer: use all customers' delays (low_history).
  - No history at all: assume payment on max(due date, as_of date) (method 'no_history').
  - Overdue invoice: only delays at least as long as the current overdue count are plausible, so we keep
    those. If every past delay was shorter than the current overdue, the invoice is already later than
    anything seen; we then count the typical delay from the as_of date (overdue_adjusted).
  - Disputed invoices get no prediction (they are not chased automatically either).

Expected receipts (the best single estimate of the money arriving each week)
  The three scenarios above put a whole invoice on one date. A backtest on 15 later dates of a public payment file
  (research/payment_ml/cashflow.py) found that spreading each invoice over the weeks it may be paid, by probability, cut the weekly
  error of the middle line from 21.3% to about 16.7% and the 2-week cumulative error from 9.7% to 4.6%. expected_receipts does that:
  the customer's own delays are blended with everyone's (weight n / (n + SHRINK_K)), delays shorter than the days already overdue are
  removed, and each invoice contributes amount x probability to every week. The early (P25) and late (P75) lines stay as they are:
  they are stress scenarios, not forecasts, and the shortfall alert still uses the late one."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from .contracts import Invoice, Prediction, Week

MIN_HISTORY = 5
SHRINK_K = 2.0        # chosen on the earlier dates of the backtest; k between 1 and 5 made little difference
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
             as_of: date, weeks: int = WEEKS, expected: list[int] | None = None) -> list[Week]:
    """Per week: expected receipts under the early (P25), middle (P50) and late (P75) scenario, and the
    money that must go out (supplier bills due that week; bills already overdue count in week 1).
    `expected` (from expected_receipts) is carried alongside as receipt_expected."""
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
             receipt_expected=expected[i] if expected is not None else None,
             obligations=obligations[i], gap_p75=max(obligations[i] - receipts["p75"][i], 0))
        for i in range(weeks)
    ]


def _week_probabilities(inv: Invoice, by_customer: dict[str, list[int]], everyone: Counter, total_all: int,
                        as_of: date, weeks: int, shrink_k: float) -> list[float]:
    """P(this invoice is paid in each of the next `weeks` weeks). Probability beyond the last week is not listed."""
    probs = [0.0] * weeks
    due_offset = (inv.due_date - as_of).days
    if total_all < MIN_HISTORY:                           # nothing to learn from: paid on the due date (or today if overdue)
        week = max(due_offset, 0) // 7
        if week < weeks:
            probs[week] = 1.0
        return probs
    own = Counter(by_customer.get(inv.customer_id, []))
    n = sum(own.values())
    lam = n / (n + shrink_k) if n else 0.0
    mix: dict[int, float] = defaultdict(float)
    for d, c in everyone.items():
        mix[d] += (1 - lam) * c / total_all
    for d, c in own.items():
        mix[d] += lam * c / n
    overdue = -due_offset
    kept = {d: w for d, w in mix.items() if d >= overdue}
    mass = sum(kept.values())
    if mass > 1e-9:                                       # still open: only delays at least as long as the days overdue remain
        slots = ((due_offset + d, w / mass) for d, w in kept.items())
    else:                                                 # later than anything on record: count the typical delay from today
        slots = ((max(1, d), w) for d, w in mix.items())
    for offset, w in slots:
        week = offset // 7
        if 0 <= week < weeks:
            probs[week] += w
    return probs


def expected_receipts(invoices: list[Invoice], delays: list[tuple[str, int]], as_of: date, weeks: int = WEEKS,
                      shrink_k: float = SHRINK_K) -> list[int]:
    """Expected money arriving in each of the next `weeks` weeks: sum over open invoices of amount x P(paid that week).
    Disputed invoices are left out, as in predict()."""
    by_customer = group_delays(delays)
    everyone = Counter(d for _, d in delays)
    total_all = sum(everyone.values())
    received = [0.0] * weeks
    for inv in invoices:
        if inv.dispute_status == "disputed":
            continue
        for w, p in enumerate(_week_probabilities(inv, by_customer, everyone, total_all, as_of, weeks, shrink_k)):
            received[w] += inv.remaining_amount * p
    return [round(x) for x in received]


def week_contributions(invoices: list[Invoice], delays: list[tuple[str, int]], as_of: date, weeks: int = WEEKS,
                       top: int = 8, min_probability: float = 0.005, shrink_k: float = SHRINK_K) -> list[dict]:
    """For each week, which invoices make up the expected receipts: the `top` largest by expected amount, then the count and
    amount of the rest. Lets a screen answer "why does this week show that much?" from the same numbers as expected_receipts."""
    by_customer = group_delays(delays)
    everyone = Counter(d for _, d in delays)
    total_all = sum(everyone.values())
    per_week: list[list[dict]] = [[] for _ in range(weeks)]
    for inv in invoices:
        if inv.dispute_status == "disputed":
            continue
        for w, p in enumerate(_week_probabilities(inv, by_customer, everyone, total_all, as_of, weeks, shrink_k)):
            if p >= min_probability:
                per_week[w].append({"invoice_id": inv.invoice_id, "customer_id": inv.customer_id, "display_name": inv.display_name,
                                    "remaining_amount": inv.remaining_amount, "probability": round(p, 3),
                                    "expected_amount": round(inv.remaining_amount * p)})
    out = []
    for rows in per_week:
        rows.sort(key=lambda r: r["expected_amount"], reverse=True)
        rest = rows[top:]
        out.append({"items": rows[:top], "more_count": len(rest), "more_amount": sum(r["expected_amount"] for r in rest)})
    return out


def beyond_horizon(invoices: list[Invoice], predictions: list[Prediction], as_of: date, weeks: int = WEEKS) -> dict[str, int]:
    """Receipts that land after the last forecast week, per scenario. Shown next to the chart so that
    money is never silently dropped: weeks + beyond = total still owed on the predicted invoices."""
    amount = {i.invoice_id: i.remaining_amount for i in invoices}
    out = {"p25": 0, "p50": 0, "p75": 0}
    for p in predictions:
        for key, day in (("p25", p.predicted_date_p25), ("p50", p.predicted_date_p50), ("p75", p.predicted_date_p75)):
            if _week_index(day, as_of) >= weeks:
                out[key] += amount.get(p.invoice_id, 0)
    return out


def bills_beyond_horizon(bills: list[tuple[date, int]], as_of: date, weeks: int = WEEKS) -> int:
    """Outgoings due after the last forecast week."""
    return sum(amt for due, amt in bills if _week_index(due, as_of) >= weeks)


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
