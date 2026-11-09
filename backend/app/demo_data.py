"""Demo expected outgoings for Minh Phat (made-up company, simulated data). Loaded by scripts/seed_obligations.py.

Regular costs repeat monthly. One large supplier payment is placed in the week where the pessimistic (P75)
scenario collects the least compared with the middle (P50) one, so the demo shows a shortfall alert."""
from datetime import date, timedelta

from . import forecast as forecast_engine, prediction
from .config import as_of_date
from .contracts import Week
from .forecast import Obligation, week_start
from .sources import load_invoices_and_payments

SEED_USER = "seed"
M = 1_000_000

# (label, amount, days after the Monday of week 1). Month names in the labels come from the date.
REGULAR = [
    ("Tien thue van phong", 30 * M, 3), ("Dien, nuoc, internet", 6 * M, 6),
    ("Nha cung cap A (nguyen lieu)", 45 * M, 9), ("Thue GTGT", 18 * M, 11),
    ("Luong nhan vien", 90 * M, 16), ("Bao hiem xa hoi", 22 * M, 16),
    ("Nha cung cap B (bao bi)", 38 * M, 31), ("Tien thue van phong", 30 * M, 33),
    ("Thue GTGT", 18 * M, 41), ("Luong nhan vien", 90 * M, 46),
    ("Tien thue van phong", 30 * M, 64), ("Luong nhan vien", 90 * M, 77),
]
BIG = "Thanh toan lo hang lon (demo thieu tien)"


def demo_obligations(weeks: list[Week], as_of: date) -> list[Obligation]:
    first = week_start(as_of)
    out = []
    for label, amount, offset in REGULAR:
        day = first + timedelta(days=offset)
        out.append(Obligation(description=f"{label} T{day.month}", amount=amount, due_date=day))
    # The week where waiting for the late scenario costs the most receipts.
    worst = max(weeks, key=lambda w: (w.receipt_p50 - w.receipt_p75, -w.week_start.toordinal()), default=None)
    if worst and worst.receipt_p50 > worst.receipt_p75:
        out.append(Obligation(description=BIG, amount=worst.receipt_p50,
                              due_date=worst.week_start + timedelta(days=2)))
    return out


def seed_demo_obligations(repo, as_of: date | None = None) -> int:
    """Add the demo outgoings that are not stored yet. Safe to run again. Returns how many were added."""
    as_of = as_of or as_of_date()
    invoices, payments = load_invoices_and_payments()
    open_invoices = [i for i in invoices if i.remaining_amount > 0]
    preds = prediction.predict(open_invoices, invoices, payments, as_of)
    weeks = forecast_engine.forecast(open_invoices, preds, [], as_of).weeks
    have = {(r.description, r.due_date) for r in repo.list_all() if r.created_by == SEED_USER}
    added = 0
    for ob in demo_obligations(weeks, as_of):
        if (ob.description, ob.due_date) not in have:
            repo.add(ob, SEED_USER)
            added += 1
    return added
