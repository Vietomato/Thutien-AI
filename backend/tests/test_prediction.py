import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.contracts import Invoice, Payment
from app.prediction import (MIN_HISTORY, delay_quantiles, paid_delays, percentile, predict,
                            predict_invoice)

FIX = Path(__file__).resolve().parents[2] / "fixtures"
AS_OF = date(2026, 11, 9)
QA01_DELAYS = [-2, 0, 1, 3, 5, 8, 12, 20, 35]


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def invoice(inv_id, customer, due, amount=100, remaining=0):
    return Invoice(invoice_id=inv_id, customer_id=customer, display_name=customer, due_date=due,
                   invoice_amount=amount, remaining_amount=remaining)


def payment(pay_id, inv_id, customer, day, amount=100):
    return Payment(payment_id=pay_id, invoice_id=inv_id, customer_id=customer, payment_date=day, amount=amount)


def history(customer, delays, start=date(2026, 1, 1)):
    """Paid invoices for one customer with the given delays, all paid well before AS_OF."""
    invs, pays = [], []
    for n, d in enumerate(delays):
        due = start + timedelta(days=10 * n)
        invs.append(invoice(f"{customer}-{n}", customer, due))
        pays.append(payment(f"P-{customer}-{n}", f"{customer}-{n}", customer, due + timedelta(days=d)))
    return invs, pays


# ---- QA01 -------------------------------------------------------------------------------

def test_qa01_quantiles_of_the_reference_series():
    assert delay_quantiles(QA01_DELAYS) == (1, 5, 12)


def test_percentile_interpolates_and_ignores_input_order():
    assert percentile([4, 1, 3, 2], 0.5) == 2.5
    assert percentile([7], 0.25) == 7
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_quantiles_are_never_decreasing():
    p25, p50, p75 = delay_quantiles([30, -5, 2, 2, 9, 0])
    assert p25 <= p50 <= p75


def test_qa01_prediction_dates_for_a_customer_with_enough_history():
    invs, pays = history("C-A", QA01_DELAYS)
    open_inv = invoice("OPEN-1", "C-A", date(2026, 11, 20), amount=80, remaining=80)
    [p] = predict([open_inv], invs, pays, AS_OF)
    assert (p.predicted_date_p25, p.predicted_date_p50, p.predicted_date_p75) == (
        date(2026, 11, 21), date(2026, 11, 25), date(2026, 12, 2))
    assert p.method == "customer_median" and p.history_count == 9
    assert not p.low_history and not p.overdue_adjusted


def test_qa01_on_the_shared_fixture_customer_c002():
    invs = [Invoice(**x) for x in load("invoices.json")]
    pays = [Payment(**x) for x in load("payments.json")]
    c002 = [paid for paid in paid_delays(invs, pays, AS_OF)["C002"]]
    assert delay_quantiles(c002) == (1, 5, 12)


# ---- QA02 -------------------------------------------------------------------------------

def _qa02_data():
    invs_a, pays_a = history("C-A", QA01_DELAYS)
    invs_b, pays_b = history("C-B", [2, 4])                      # only 2 paid invoices
    open_inv = invoice("OPEN-B", "C-B", date(2026, 11, 20), amount=50, remaining=50)
    return open_inv, invs_a + invs_b, pays_a + pays_b


def test_qa02_customer_with_two_invoices_uses_global_history_and_is_low_confidence():
    open_inv, invs, pays = _qa02_data()
    [p] = predict([open_inv], invs, pays, AS_OF)
    assert p.method == "global_median" and p.low_history
    assert p.history_count == 2
    # global pool = the 9 reference delays + 2 and 4
    assert delay_quantiles(QA01_DELAYS + [2, 4]) == (2, 4, 10)
    assert p.predicted_date_p50 == date(2026, 11, 24)


def test_qa02_a_payment_after_as_of_changes_nothing():
    open_inv, invs, pays = _qa02_data()
    before = predict([open_inv], invs, pays, AS_OF)
    # a future payment completes a third invoice for C-B; it is unknown at AS_OF
    future_inv = invoice("C-B-future", "C-B", AS_OF - timedelta(days=5))
    future_pay = payment("P-future", "C-B-future", "C-B", AS_OF + timedelta(days=30))
    after = predict([open_inv], invs + [future_inv], pays + [future_pay], AS_OF)
    assert after == before


# ---- rules around history ---------------------------------------------------------------

def test_exactly_min_history_uses_the_customer_own_numbers():
    invs, pays = history("C-A", [1, 2, 3, 4, 5][:MIN_HISTORY])
    other_invs, other_pays = history("C-Z", [40] * 10)
    open_inv = invoice("OPEN", "C-A", date(2026, 11, 20), remaining=10)
    [p] = predict([open_inv], invs + other_invs, pays + other_pays, AS_OF)
    assert p.method == "customer_median" and p.predicted_date_p50 == date(2026, 11, 23)


def test_no_history_at_all_assumes_payment_on_the_due_date():
    open_inv = invoice("OPEN", "C-NEW", date(2026, 11, 20), remaining=10)
    [p] = predict([open_inv], [], [], AS_OF)
    assert p.method == "no_history" and p.low_history and p.history_count == 0
    assert p.predicted_date_p25 == p.predicted_date_p50 == p.predicted_date_p75 == date(2026, 11, 20)


def test_partly_paid_invoices_do_not_count_as_history():
    inv = invoice("PART", "C-A", date(2026, 9, 1), amount=100, remaining=60)
    pay = payment("P1", "PART", "C-A", date(2026, 9, 3), amount=40)
    assert paid_delays([inv], [pay], AS_OF) == {}


def test_invoice_paid_in_two_installments_is_dated_by_the_last_one():
    inv = invoice("SPLIT", "C-A", date(2026, 9, 1), amount=100)
    pays = [payment("P1", "SPLIT", "C-A", date(2026, 9, 3), 40), payment("P2", "SPLIT", "C-A", date(2026, 9, 11), 60)]
    assert paid_delays([inv], pays, AS_OF) == {"C-A": [10]}


def test_history_is_cut_at_as_of_for_the_second_installment_too():
    inv = invoice("SPLIT", "C-A", date(2026, 11, 1), amount=100)
    pays = [payment("P1", "SPLIT", "C-A", date(2026, 11, 3), 40), payment("P2", "SPLIT", "C-A", date(2026, 11, 20), 60)]
    assert paid_delays([inv], pays, AS_OF) == {}


# ---- dates already in the past ----------------------------------------------------------

def test_a_predicted_date_in_the_past_is_clamped_to_as_of_and_flagged():
    invs, pays = history("C-A", [1, 2, 3, 4, 5, 6])
    overdue = invoice("OLD", "C-A", date(2026, 10, 1), remaining=10)        # 39 days overdue
    [p] = predict([overdue], invs, pays, AS_OF)
    assert p.overdue_adjusted
    assert p.predicted_date_p25 == p.predicted_date_p50 == p.predicted_date_p75 == AS_OF


def test_a_future_prediction_is_not_flagged():
    invs, pays = history("C-A", [1, 2, 3, 4, 5, 6])
    [p] = predict([invoice("NEW", "C-A", date(2026, 11, 20), remaining=10)], invs, pays, AS_OF)
    assert not p.overdue_adjusted


def test_dates_are_ordered_and_every_open_invoice_gets_a_prediction():
    invs = [Invoice(**x) for x in load("invoices.json")]
    pays = [Payment(**x) for x in load("payments.json")]
    opens = [i for i in invs if i.remaining_amount > 0]
    result = predict(opens, invs, pays, AS_OF)
    assert [p.invoice_id for p in result] == [i.invoice_id for i in opens]
    for p in result:
        assert p.predicted_date_p25 <= p.predicted_date_p50 <= p.predicted_date_p75
        assert p.predicted_date_p25 >= AS_OF


def test_closed_invoices_get_no_prediction():
    closed = invoice("DONE", "C-A", date(2026, 11, 20), remaining=0)
    assert predict([closed], [], [], AS_OF) == []


def test_predict_invoice_is_deterministic():
    inv = invoice("OPEN", "C-A", date(2026, 11, 20), remaining=10)
    assert predict_invoice(inv, AS_OF, QA01_DELAYS, []) == predict_invoice(inv, AS_OF, QA01_DELAYS, [])
