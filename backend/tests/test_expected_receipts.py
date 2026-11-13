"""Expected receipts: each invoice is spread over the weeks it may be paid, by probability. Hand-calculated cases."""
from datetime import date

import pytest

from app import analytics
from app.contracts import Invoice

AS_OF = date(2026, 11, 9)


def inv(invoice_id="I1", customer="C1", due=AS_OF, amount=100, dispute="none"):
    return Invoice(invoice_id=invoice_id, customer_id=customer, display_name="X", due_date=due, invoice_amount=amount,
                   remaining_amount=amount, dispute_status=dispute)


def test_a_customer_who_always_pays_ten_days_late_lands_in_the_second_week():
    delays = [("C1", 10)] * 6
    weeks = analytics.expected_receipts([inv(amount=100)], delays, AS_OF)
    assert weeks[1] == 100 and sum(weeks) == 100                    # due today + 10 days = day 10 = week 2 (days 7-13)


def test_an_invoice_is_split_by_probability_not_put_on_one_date():
    delays = [("C1", 0)] * 5 + [("C1", 14)] * 5                      # half the time on time, half two weeks late
    weeks = analytics.expected_receipts([inv(amount=100)], delays, AS_OF, shrink_k=0)
    assert weeks[0] == 50 and weeks[2] == 50 and sum(weeks) == 100


def test_the_old_rule_would_have_put_everything_in_one_week():
    delays = [("C1", 0)] * 5 + [("C1", 14)] * 5
    invoices = [inv(amount=100)]
    weeks = analytics.forecast(invoices, analytics.predict(invoices, delays, AS_OF), [], AS_OF,
                               expected=analytics.expected_receipts(invoices, delays, AS_OF, shrink_k=0))
    assert max(w.receipt_p50 for w in weeks) == 100                  # the median date carries the whole invoice
    assert [w.receipt_expected for w in weeks][:3] == [50, 0, 50]


def test_an_overdue_invoice_can_only_be_paid_after_the_days_already_overdue():
    delays = [("C1", 0)] * 5 + [("C1", 14)] * 5
    late = inv(due=date(2026, 11, 4), amount=100)                    # 5 days overdue: the on-time half is no longer possible
    weeks = analytics.expected_receipts([late], delays, AS_OF, shrink_k=0)
    assert weeks[1] == 100                                           # due 4/11 + 14 days = 18/11 = day 9 from today: second week
    assert weeks[0] == 0


def test_a_short_history_is_blended_with_everyones():
    delays = [("C1", 30)] + [("other", 0)] * 20                      # C1 has one invoice, paid 30 days late
    weeks = analytics.expected_receipts([inv(customer="C1", amount=300)], delays, AS_OF, shrink_k=2)
    # lambda = 1 / (1 + 2): a third of the weight follows C1 (30 days late), two thirds follow everyone's (21 delays, 20 of them on time)
    assert weeks[4] == 110                                           # 300 x (2/3 x 1/21 + 1/3): day 30 is in the fifth week
    assert weeks[0] == 190                                           # 300 x 2/3 x 20/21


def test_a_long_history_is_trusted():
    delays = [("C1", 30)] * 40 + [("other", 0)] * 20
    weeks = analytics.expected_receipts([inv(customer="C1", amount=1000)], delays, AS_OF, shrink_k=2)
    assert weeks[4] > 900


def test_later_than_anything_on_record_counts_the_typical_delay_from_today():
    delays = [("C1", 1)] * 6
    far = inv(due=date(2026, 9, 1), amount=100)                      # 69 days overdue: later than every past delay
    weeks = analytics.expected_receipts([far], delays, AS_OF)
    assert weeks[0] == 100                                           # 1 day from today


def test_disputed_invoices_and_the_far_future_are_left_out():
    delays = [("C1", 0)] * 6
    weeks = analytics.expected_receipts([inv("D", amount=70, dispute="disputed"), inv("F", due=date(2027, 6, 1), amount=100)], delays, AS_OF)
    assert sum(weeks) == 0


def test_with_no_payment_history_an_invoice_is_expected_on_its_due_date():
    weeks = analytics.expected_receipts([inv(due=date(2026, 11, 20), amount=100)], [], AS_OF)
    assert weeks[1] == 100                                           # 11 days out


def test_everything_inside_the_horizon_is_counted_exactly_once():
    delays = [("C1", 0)] * 3 + [("C1", 3)] * 3 + [("C1", 9)] * 3
    invoices = [inv("A", amount=120), inv("B", amount=80, due=date(2026, 11, 12))]
    assert sum(analytics.expected_receipts(invoices, delays, AS_OF)) == 200


def test_forecast_carries_the_expected_figure_next_to_the_old_lines():
    delays = [("C1", 0)] * 5
    invoices = [inv(amount=100)]
    weeks = analytics.forecast(invoices, analytics.predict(invoices, delays, AS_OF), [], AS_OF, expected=[7] * 12)
    assert all(w.receipt_expected == 7 for w in weeks)
    assert weeks[0].receipt_p25 == weeks[0].receipt_p50 == weeks[0].receipt_p75 == 100   # the three scenarios are untouched
    assert analytics.forecast(invoices, [], [], AS_OF)[0].receipt_expected is None       # optional


@pytest.mark.parametrize("k", [0, 1, 2, 5, 20])
def test_the_split_never_creates_or_loses_money(k):
    delays = [("C1", d) for d in (0, 1, 2, 5, 8, 15, 22, 40)] + [("O", 3)] * 10
    invoices = [inv("A", amount=1000, due=date(2026, 11, 2)), inv("B", customer="O", amount=500, due=date(2026, 11, 20))]
    got = analytics.expected_receipts(invoices, delays, AS_OF, shrink_k=k)
    assert abs(sum(got) - 1500) <= 6       # rounding each of the 12 weeks is the only difference: all of this lands inside 12 weeks


def test_the_forecast_endpoint_returns_the_expected_figure_and_keeps_the_old_ones(client, team, auth, fake_odoo):
    weeks = client.get("/api/forecast", headers=auth("acc1")).json()["weeks"]
    assert len(weeks) == 12
    assert all(isinstance(w["receipt_expected"], int) for w in weeks)
    assert all(key in weeks[0] for key in ("receipt_p25", "receipt_p50", "receipt_p75", "obligations", "gap_p75"))
    assert sum(w["receipt_expected"] for w in weeks) > 0


# ---- which invoices make up a week ----

def test_each_week_lists_its_invoices_largest_first_with_the_probability():
    delays = [("C1", 0)] * 5 + [("C1", 14)] * 5
    invoices = [inv("A", amount=100), inv("B", amount=300)]
    weeks = analytics.week_contributions(invoices, delays, AS_OF, shrink_k=0)
    first = weeks[0]["items"]
    assert [r["invoice_id"] for r in first] == ["B", "A"]                       # 150 before 50
    assert first[0]["probability"] == 0.5 and first[0]["expected_amount"] == 150
    assert [r["invoice_id"] for r in weeks[2]["items"]] == ["B", "A"]           # the other half, two weeks later
    assert weeks[1]["items"] == []


def test_the_listed_invoices_add_up_to_the_expected_week_figure():
    delays = [("C1", d) for d in (0, 1, 3, 6, 9, 12, 20)] + [("O", 2)] * 6
    invoices = [inv(f"I{i}", customer="C1" if i % 2 else "O", amount=100 + i, due=date(2026, 11, 3 + i)) for i in range(20)]
    expected = analytics.expected_receipts(invoices, delays, AS_OF)
    detail = analytics.week_contributions(invoices, delays, AS_OF, top=3, min_probability=0.0)
    for w in range(12):
        listed = sum(r["expected_amount"] for r in detail[w]["items"]) + detail[w]["more_amount"]
        assert abs(listed - expected[w]) <= 20          # each invoice is rounded on its own


def test_the_rest_of_a_busy_week_is_counted_not_dropped():
    delays = [("C1", 0)] * 6
    invoices = [inv(f"I{i}", amount=10 + i) for i in range(12)]
    week0 = analytics.week_contributions(invoices, delays, AS_OF, top=5)[0]
    assert len(week0["items"]) == 5 and week0["more_count"] == 7
    assert sum(r["expected_amount"] for r in week0["items"]) + week0["more_amount"] == sum(10 + i for i in range(12))


def test_disputed_invoices_are_not_listed():
    delays = [("C1", 0)] * 6
    detail = analytics.week_contributions([inv("D", amount=70, dispute="disputed")], delays, AS_OF)
    assert all(week["items"] == [] for week in detail)


def test_the_endpoint_returns_the_invoices_behind_each_week(client, team, auth, fake_odoo):
    f = client.get("/api/forecast", headers=auth("acc1")).json()
    assert len(f["week_invoices"]) == 12
    listed = [r for week in f["week_invoices"] for r in week["items"]]
    assert listed and {"invoice_id", "display_name", "probability", "expected_amount"} <= set(listed[0])
