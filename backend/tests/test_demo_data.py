from datetime import date, datetime, timezone

from app import forecast as forecast_engine, prediction
from app.contracts import Week
from app.demo_data import BIG, SEED_USER, demo_obligations, seed_demo_obligations
from app.forecast import Obligation
from app.obligations import ObligationRecord
from app.sources import load_invoices_and_payments

AS_OF = date(2026, 11, 9)


class MemoryRepo:
    def __init__(self):
        self.rows = []

    def add(self, ob: Obligation, created_by: str):
        rec = ObligationRecord(id=len(self.rows) + 1, description=ob.description, amount=ob.amount,
                               due_date=ob.due_date, created_by=created_by,
                               created_at=datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.rows.append(rec)
        return rec

    def list_all(self):
        return list(self.rows)


def week(start, p25, p50, p75):
    return Week(week_start=start, receipt_p25=p25, receipt_p50=p50, receipt_p75=p75, obligations=0, gap_p75=0)


def test_between_ten_and_fifteen_outgoings_all_valid():
    weeks = [week(date(2026, 11, 9), 0, 40, 0)]
    items = demo_obligations(weeks, AS_OF)
    assert 10 <= len(items) <= 15
    assert all(o.amount > 0 and o.description for o in items)


def test_the_large_payment_lands_in_the_week_where_p75_collects_least_against_p50():
    weeks = [week(date(2026, 11, 9), 100, 100, 100), week(date(2026, 11, 16), 65, 40, 0),
             week(date(2026, 11, 23), 0, 25, 20)]
    big = [o for o in demo_obligations(weeks, AS_OF) if o.description == BIG]
    assert len(big) == 1 and big[0].amount == 40                  # that week's P50 receipts
    assert date(2026, 11, 16) <= big[0].due_date < date(2026, 11, 23)


def test_no_large_payment_when_no_week_shifts_money_later():
    weeks = [week(date(2026, 11, 9), 10, 10, 10)]
    assert all(o.description != BIG for o in demo_obligations(weeks, AS_OF))


def test_seeding_twice_adds_nothing_the_second_time():
    repo = MemoryRepo()
    first = seed_demo_obligations(repo, AS_OF)
    assert first == len(repo.rows) >= 10
    assert seed_demo_obligations(repo, AS_OF) == 0
    assert len(repo.rows) == first
    assert {r.created_by for r in repo.rows} == {SEED_USER}


def test_the_demo_data_really_triggers_a_shortfall_alert_on_the_fixtures(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "fixture")
    repo = MemoryRepo()
    seed_demo_obligations(repo, AS_OF)
    invoices, payments = load_invoices_and_payments()
    opens = [i for i in invoices if i.remaining_amount > 0]
    preds = prediction.predict(opens, invoices, payments, AS_OF)
    result = forecast_engine.forecast(opens, preds, list(repo.rows), AS_OF)
    assert any(w.gap_p75 > 0 for w in result.weeks)
    big_week = next(w for w in result.weeks if w.week_start == date(2026, 11, 23))
    assert big_week.gap_p75 > 0 and big_week.receipt_p50 > 0
