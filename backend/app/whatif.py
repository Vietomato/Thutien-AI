"""What-if scenarios on the 12-week forecast. Pure functions: no database, no network, no LLM.

A scenario changes some inputs of the forecast and the same forecast code is run again:
  - customer_shifts: every predicted payment date of a customer moves by N days (later or earlier);
  - pay_now: a customer pays everything this week;
  - defer: an outgoing (supplier bill or typed expense) is paid N days later;
  - extra_outgoings: a hypothetical new payment (amount, date).
The result compares the base forecast with the scenario, week by week, using the same alert rule as the product
(the late scenario against outgoings)."""
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import analytics
from .contracts import Invoice, Prediction, Week

PAY_NOW_SHIFT = -10_000            # "as early as possible": every date is clamped to today


@dataclass(frozen=True)
class Outgoing:
    key: str                       # "bill:3" (Odoo supplier bill, numbered in due-date order) or "manual:5" (typed expense id)
    source: str                    # "odoo" | "manual"
    description: str
    amount: int
    due_date: date
    fee_pct_per_month: float | None = None   # late-payment fee, only known for typed expenses where the accountant entered it


@dataclass
class Scenario:
    customer_shifts: dict[str, int] = field(default_factory=dict)      # customer id -> extra days of delay (negative = earlier)
    pay_now: set[str] = field(default_factory=set)                     # customer ids that pay everything this week
    defer: dict[str, int] = field(default_factory=dict)                # outgoing key -> days later
    extra_outgoings: list[tuple[date, int, str]] = field(default_factory=list)   # (due date, amount, label)

    def is_empty(self) -> bool:
        return not (self.customer_shifts or self.pay_now or self.defer or self.extra_outgoings)


def outgoings_from(bills: list[tuple[date, int]], manual: list[dict]) -> list[Outgoing]:
    """Supplier bills carry only a due date and an amount in Odoo (no supplier name, no fee terms), so they are numbered."""
    out = [Outgoing(key=f"bill:{i}", source="odoo", description=f"Hóa đơn nhà cung cấp trong Odoo, hạn {due.strftime('%d/%m/%Y')}",
                    amount=int(amount), due_date=due)
           for i, (due, amount) in enumerate(sorted(bills, key=lambda b: (b[0], b[1])), start=1)]
    for row in manual:
        fee = row.get("late_fee_percent_per_month")
        out.append(Outgoing(key=f"manual:{row['id']}", source="manual", description=str(row["description"]), amount=int(row["amount"]),
                            due_date=row["due_date"] if isinstance(row["due_date"], date) else date.fromisoformat(str(row["due_date"])),
                            fee_pct_per_month=float(fee) if fee is not None else None))
    return out


def week_index(day: date, as_of: date) -> int:
    return max((day - as_of).days // 7, 0)


def _shifted_predictions(predictions: list[Prediction], invoices: list[Invoice], shifts: dict[str, int], as_of: date) -> list[Prediction]:
    owner = {i.invoice_id: i.customer_id for i in invoices}
    out = []
    for p in predictions:
        days = shifts.get(owner.get(p.invoice_id, ""), 0)
        if not days:
            out.append(p)
            continue
        move = lambda d: max(d + timedelta(days=days), as_of)           # a payment cannot move before today
        out.append(p.model_copy(update={"predicted_date_p25": move(p.predicted_date_p25), "predicted_date_p50": move(p.predicted_date_p50),
                                         "predicted_date_p75": move(p.predicted_date_p75)}))
    return out


def _effective_shifts(scenario: Scenario | None) -> dict[str, int]:
    if not scenario:
        return {}
    shifts = dict(scenario.customer_shifts)
    for customer in scenario.pay_now:
        shifts[customer] = PAY_NOW_SHIFT
    return shifts


def outgoing_pairs(outgoings: list[Outgoing], scenario: Scenario | None = None) -> list[tuple[date, int]]:
    pairs = []
    for o in outgoings:
        days = scenario.defer.get(o.key, 0) if scenario else 0
        pairs.append((o.due_date + timedelta(days=days), o.amount))
    if scenario:
        pairs += [(due, amount) for due, amount, _ in scenario.extra_outgoings]
    return pairs


def run_forecast(invoices: list[Invoice], delays: list[tuple[str, int]], outgoings: list[Outgoing], as_of: date,
                 scenario: Scenario | None = None) -> list[Week]:
    """The product's forecast (early / usual / late lines, expected receipts, outgoings, gap), under an optional scenario."""
    shifts = _effective_shifts(scenario)
    predictions = _shifted_predictions(analytics.predict(invoices, delays, as_of), invoices, shifts, as_of)
    expected = analytics.expected_receipts(invoices, delays, as_of, shifts=shifts)
    return analytics.forecast(invoices, predictions, outgoing_pairs(outgoings, scenario), as_of, expected=expected)


def with_outgoings(weeks: list[Week], outgoings: list[Outgoing], as_of: date, scenario: Scenario) -> list[Week]:
    """Same receipts, different outgoings: cheaper than a full re-run when only payments move (defer analysis)."""
    amounts = [0] * len(weeks)
    for due, amount in outgoing_pairs(outgoings, scenario):
        idx = week_index(due, as_of)
        if idx < len(weeks):
            amounts[idx] += amount
    return [w.model_copy(update={"obligations": amounts[i], "gap_p75": max(amounts[i] - w.receipt_p75, 0)}) for i, w in enumerate(weeks)]


def summarize(weeks: list[Week]) -> dict:
    gaps = [(w.gap_p75, i) for i, w in enumerate(weeks) if w.gap_p75 > 0]
    worst = max(gaps)[1] if gaps else None
    return {
        "risky_weeks": len(gaps),
        "risky_week_numbers": [i + 1 for _, i in gaps],
        "total_gap": sum(g for g, _ in gaps),
        "worst_week": ({"week": worst + 1, "week_start": weeks[worst].week_start.isoformat(), "gap": weeks[worst].gap_p75} if worst is not None else None),
    }


def _row(i: int, before: Week, after: Week) -> dict:
    return {"week": i + 1, "week_start": before.week_start.isoformat(), "week_end": (before.week_start + timedelta(days=6)).isoformat(),
            "late_receipts_before": before.receipt_p75, "late_receipts_after": after.receipt_p75,
            "expected_receipts_before": before.receipt_expected, "expected_receipts_after": after.receipt_expected,
            "obligations_before": before.obligations, "obligations_after": after.obligations,
            "gap_before": before.gap_p75, "gap_after": after.gap_p75}


def compare(base: list[Week], scenario: list[Week]) -> dict:
    """Base against scenario: the totals, and the weeks where anything changed (with the weeks that became short or stopped being short)."""
    changed = [_row(i, b, s) for i, (b, s) in enumerate(zip(base, scenario))
               if (b.receipt_p75, b.receipt_expected, b.obligations, b.gap_p75) != (s.receipt_p75, s.receipt_expected, s.obligations, s.gap_p75)]
    base_short = {i for i, w in enumerate(base) if w.gap_p75 > 0}
    new_short = {i for i, w in enumerate(scenario) if w.gap_p75 > 0}
    return {"base": summarize(base), "scenario": summarize(scenario), "changed_weeks": changed,
            "newly_short_weeks": sorted(i + 1 for i in new_short - base_short), "no_longer_short_weeks": sorted(i + 1 for i in base_short - new_short)}


def defer_options(invoices: list[Invoice], delays: list[tuple[str, int]], outgoings: list[Outgoing], as_of: date, defer_days: int,
                  horizon_weeks: int = analytics.WEEKS, top: int = 12) -> dict:
    """For each outgoing: what happens to the shortfall if it is paid `defer_days` later, and the late fee if that is known.
    The fee is amount x monthly rate x days / 30, only for outgoings where the accountant entered a rate."""
    base = run_forecast(invoices, delays, outgoings, as_of)
    base_summary = summarize(base)
    rows = []
    for o in outgoings:
        if week_index(o.due_date, as_of) >= horizon_weeks:
            continue                                                    # not in the forecast window: deferring it changes nothing there
        after = with_outgoings(base, outgoings, as_of, Scenario(defer={o.key: defer_days}))
        s = summarize(after)
        fee = round(o.amount * o.fee_pct_per_month / 100 * defer_days / 30) if o.fee_pct_per_month is not None else None
        rows.append({"outgoing": o.key, "source": o.source, "description": o.description, "amount": o.amount, "due_date": o.due_date.isoformat(),
                     "week": week_index(o.due_date, as_of) + 1, "fee_pct_per_month": o.fee_pct_per_month, "fee_known": fee is not None,
                     "estimated_fee": fee, "total_gap_after": s["total_gap"], "gap_reduction": base_summary["total_gap"] - s["total_gap"],
                     "risky_weeks_after": s["risky_weeks"],
                     "weeks_no_longer_short": sorted(set(base_summary["risky_week_numbers"]) - set(s["risky_week_numbers"])),
                     "weeks_newly_short": sorted(set(s["risky_week_numbers"]) - set(base_summary["risky_week_numbers"]))})
    helpful = sorted((r for r in rows if r["gap_reduction"] > 0), key=lambda r: (-r["gap_reduction"], r["amount"] * -1))
    cheapest = sorted((r for r in helpful if r["fee_known"]), key=lambda r: (r["estimated_fee"], -r["gap_reduction"]))
    return {"defer_days": defer_days, "base": base_summary, "outgoings_checked": len(rows), "helpful_count": len(helpful),
            "most_relief": helpful[:top], "lowest_known_fee": cheapest[:top], "helpful_without_fee_info": sum(1 for r in helpful if not r["fee_known"])}
