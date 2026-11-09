from datetime import date

import pytest
from pydantic import ValidationError

from app.contracts import Invoice, Prediction
from app.forecast import Obligation, forecast, week_start

AS_OF = date(2026, 11, 9)          # a Monday
M = 1_000_000


def invoice(inv_id, remaining):
    return Invoice(invoice_id=inv_id, customer_id="C", display_name="C", due_date=date(2026, 11, 1),
                   invoice_amount=remaining, remaining_amount=remaining)


def pred(inv_id, p25, p50, p75):
    return Prediction(invoice_id=inv_id, as_of_date=AS_OF, predicted_date_p25=p25, predicted_date_p50=p50,
                      predicted_date_p75=p75, history_count=9, method="customer_median",
                      low_history=False, overdue_adjusted=False)


def spend(day, amount, what="chi"):
    return Obligation(description=what, amount=amount, due_date=day)


A = (invoice("A", 80 * M), pred("A", date(2026, 11, 10), date(2026, 11, 13), date(2026, 11, 17)))
B = (invoice("B", 20 * M), pred("B", date(2026, 11, 11), date(2026, 11, 14), date(2026, 11, 18)))


def receipts(week):
    return (week.receipt_p25, week.receipt_p50, week.receipt_p75)


# ---- QA03 -------------------------------------------------------------------------------

def test_qa03_one_customer_one_expense():
    f = forecast([A[0]], [A[1]], [spend(date(2026, 11, 12), 50 * M)], AS_OF)
    w1, w2 = f.weeks[0], f.weeks[1]
    assert w1.week_start == date(2026, 11, 9) and w2.week_start == date(2026, 11, 16)
    assert receipts(w1) == (80 * M, 80 * M, 0)
    assert w1.obligations == 50 * M and w1.gap_p75 == 50 * M
    assert receipts(w2) == (0, 0, 80 * M)
    assert w2.obligations == 0 and w2.gap_p75 == 0


# ---- QA04 -------------------------------------------------------------------------------

def test_qa04_two_customers_late_together():
    f = forecast([A[0], B[0]], [A[1], B[1]],
                 [spend(date(2026, 11, 11), 50 * M), spend(date(2026, 11, 13), 40 * M)], AS_OF)
    w1, w2 = f.weeks[0], f.weeks[1]
    assert receipts(w1) == (100 * M, 100 * M, 0)
    assert w1.obligations == 90 * M and w1.gap_p75 == 90 * M
    assert receipts(w2) == (0, 0, 100 * M)


# ---- QA05 -------------------------------------------------------------------------------

def test_qa05_gap_is_expense_minus_p75_receipts():
    inv = invoice("X", 40 * M)
    p = pred("X", date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12))     # all in week 1
    f = forecast([inv], [p], [spend(date(2026, 11, 13), 70 * M)], AS_OF)
    assert f.weeks[0].receipt_p75 == 40 * M and f.weeks[0].gap_p75 == 30 * M


def test_no_gap_when_receipts_cover_the_expense():
    f = forecast([A[0]], [A[1]], [spend(date(2026, 11, 20), 50 * M)], AS_OF)   # week 2: P75 brings 80
    assert f.weeks[1].gap_p75 == 0


# ---- QA06 -------------------------------------------------------------------------------

def test_qa06_money_beyond_twelve_weeks_is_reported_not_dropped():
    inside = (invoice("IN", 30 * M), pred("IN", date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 20)))
    far = (invoice("FAR", 70 * M), pred("FAR", date(2026, 11, 20), date(2027, 2, 20), date(2027, 3, 20)))
    f = forecast([inside[0], far[0]], [inside[1], far[1]], [], AS_OF)
    # 12 weeks from Mon 09/11/2026 end on Sun 31/01/2027: FAR p50 and p75 fall after that.
    assert f.receipts_out_of_horizon.p25 == 0
    assert f.receipts_out_of_horizon.p50 == 70 * M and f.receipts_out_of_horizon.p75 == 70 * M
    total = 100 * M
    for key in ("p25", "p50", "p75"):
        in_weeks = sum(getattr(w, f"receipt_{key}") for w in f.weeks)
        assert in_weeks + getattr(f.receipts_out_of_horizon, key) == total


def test_every_scenario_conserves_the_total():
    invs = [A[0], B[0]]
    f = forecast(invs, [A[1], B[1]], [], AS_OF)
    for key in ("p25", "p50", "p75"):
        assert sum(getattr(w, f"receipt_{key}") for w in f.weeks) + getattr(f.receipts_out_of_horizon, key) == 100 * M


# ---- week boundaries and expenses -------------------------------------------------------

def test_weeks_start_on_monday_and_there_are_twelve_by_default():
    f = forecast([], [], [], date(2026, 11, 11))                      # a Wednesday
    assert len(f.weeks) == 12
    assert f.weeks[0].week_start == date(2026, 11, 9)
    assert all(w.week_start.weekday() == 0 for w in f.weeks)
    assert week_start(date(2026, 11, 15)) == date(2026, 11, 9)         # Sunday belongs to the same week
    assert week_start(date(2026, 11, 16)) == date(2026, 11, 16)


def test_sunday_and_monday_land_in_different_weeks():
    inv = invoice("S", 10 * M)
    p = pred("S", date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 16))
    f = forecast([inv], [p], [], AS_OF)
    assert f.weeks[0].receipt_p25 == 10 * M and f.weeks[0].receipt_p50 == 0
    assert f.weeks[1].receipt_p50 == 10 * M


def test_an_expense_already_late_counts_in_week_one():
    f = forecast([], [], [spend(date(2026, 10, 1), 5 * M)], AS_OF)
    assert f.weeks[0].obligations == 5 * M


def test_an_expense_after_the_last_week_is_reported_separately():
    f = forecast([], [], [spend(date(2027, 6, 1), 5 * M)], AS_OF)
    assert sum(w.obligations for w in f.weeks) == 0 and f.obligations_out_of_horizon == 5 * M


def test_expenses_in_the_same_week_are_added_up():
    f = forecast([], [], [spend(date(2026, 11, 10), 3 * M), spend(date(2026, 11, 14), 4 * M)], AS_OF)
    assert f.weeks[0].obligations == 7 * M


def test_no_data_gives_twelve_zero_weeks():
    f = forecast([], [], [], AS_OF)
    assert all(receipts(w) == (0, 0, 0) and w.obligations == 0 and w.gap_p75 == 0 for w in f.weeks)


def test_a_prediction_for_an_unknown_invoice_is_an_error():
    with pytest.raises(ValueError):
        forecast([], [A[1]], [], AS_OF)


def test_an_expense_must_be_positive():
    with pytest.raises(ValidationError):
        Obligation(description="x", amount=0, due_date=AS_OF)
    with pytest.raises(ValidationError):
        Obligation(description="x", amount=-5, due_date=AS_OF)
