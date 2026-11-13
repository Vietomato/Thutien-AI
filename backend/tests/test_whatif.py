"""What-if scenarios: hand-calculated cases. No database, no network."""
from datetime import date

import pytest

from app import analytics, whatif
from app.contracts import Invoice
from app.whatif import Outgoing, Scenario

AS_OF = date(2026, 11, 9)
M = 1_000_000


def inv(invoice_id="I1", customer="C1", due=AS_OF, amount=100 * M, dispute="none"):
    return Invoice(invoice_id=invoice_id, customer_id=customer, display_name=f"Khach {customer}", due_date=due, invoice_amount=amount,
                   remaining_amount=amount, dispute_status=dispute)


ON_TIME = [("C1", 0)] * 6 + [("C2", 0)] * 6          # everybody pays on the due date


def out(key="bill:1", amount=80 * M, due=AS_OF, fee=None, source="odoo"):
    return Outgoing(key=key, source=source, description=key, amount=amount, due_date=due, fee_pct_per_month=fee)


def test_a_customer_paying_ten_days_later_moves_the_money_to_the_next_week_and_creates_a_shortfall():
    invoices = [inv(due=AS_OF)]                                  # 100 due today, pays on time: week 1
    outgoings = [out(amount=80 * M, due=AS_OF)]
    base = whatif.run_forecast(invoices, ON_TIME, outgoings, AS_OF)
    scen = whatif.run_forecast(invoices, ON_TIME, outgoings, AS_OF, Scenario(customer_shifts={"C1": 10}))
    assert base[0].receipt_p75 == 100 * M and base[0].gap_p75 == 0
    assert scen[0].receipt_p75 == 0 and scen[1].receipt_p75 == 100 * M and scen[0].gap_p75 == 80 * M
    result = whatif.compare(base, scen)
    assert result["newly_short_weeks"] == [1] and result["no_longer_short_weeks"] == []
    assert result["scenario"]["total_gap"] == 80 * M and result["base"]["total_gap"] == 0
    assert [w["week"] for w in result["changed_weeks"]] == [1, 2]


def test_the_expected_line_moves_with_the_customer_too():
    invoices = [inv(due=AS_OF)]
    base = whatif.run_forecast(invoices, ON_TIME, [], AS_OF)
    scen = whatif.run_forecast(invoices, ON_TIME, [], AS_OF, Scenario(customer_shifts={"C1": 10}))
    assert base[0].receipt_expected == 100 * M and scen[1].receipt_expected == 100 * M


def test_only_the_named_customer_moves():
    invoices = [inv("A", "C1", amount=100 * M), inv("B", "C2", amount=50 * M)]
    scen = whatif.run_forecast(invoices, ON_TIME, [], AS_OF, Scenario(customer_shifts={"C1": 10}))
    assert scen[0].receipt_p75 == 50 * M and scen[1].receipt_p75 == 100 * M


def test_a_payment_never_moves_into_the_past():
    invoices = [inv(due=AS_OF)]
    scen = whatif.run_forecast(invoices, ON_TIME, [], AS_OF, Scenario(customer_shifts={"C1": -20}))
    assert scen[0].receipt_p75 == 100 * M and sum(w.receipt_p75 for w in scen) == 100 * M


def test_paying_everything_now_brings_a_future_invoice_into_this_week():
    invoices = [inv(due=date(2026, 12, 9))]                        # due in 30 days: week 5 normally
    base = whatif.run_forecast(invoices, ON_TIME, [], AS_OF)
    scen = whatif.run_forecast(invoices, ON_TIME, [], AS_OF, Scenario(pay_now={"C1"}))
    assert base[4].receipt_p75 == 100 * M and base[0].receipt_p75 == 0
    assert scen[0].receipt_p75 == 100 * M and scen[4].receipt_p75 == 0 and scen[0].receipt_expected == 100 * M


def test_deferring_a_bill_moves_it_to_a_later_week():
    invoices = [inv(due=date(2026, 11, 17))]                       # 100 arrives in week 2
    outgoings = [out(amount=80 * M, due=AS_OF)]
    base = whatif.run_forecast(invoices, ON_TIME, outgoings, AS_OF)
    scen = whatif.run_forecast(invoices, ON_TIME, outgoings, AS_OF, Scenario(defer={"bill:1": 7}))
    assert base[0].gap_p75 == 80 * M and scen[0].obligations == 0 and scen[1].obligations == 80 * M and scen[1].gap_p75 == 0
    assert whatif.compare(base, scen)["no_longer_short_weeks"] == [1]


def test_a_hypothetical_payment_can_create_a_shortfall():
    invoices = [inv(due=AS_OF)]
    base = whatif.run_forecast(invoices, ON_TIME, [], AS_OF)
    scen = whatif.run_forecast(invoices, ON_TIME, [], AS_OF, Scenario(extra_outgoings=[(date(2026, 11, 20), 500 * M, "may moi")]))
    assert whatif.summarize(base)["risky_weeks"] == 0
    assert whatif.summarize(scen)["risky_week_numbers"] == [2] and whatif.summarize(scen)["total_gap"] == 500 * M


def test_summary_names_the_worst_week():
    weeks = whatif.run_forecast([inv(due=AS_OF)], ON_TIME, [out(amount=300 * M, due=date(2026, 11, 24)), out("bill:2", 40 * M, date(2026, 11, 10))], AS_OF)
    worst = whatif.summarize(weeks)["worst_week"]
    assert worst["week"] == 3 and worst["gap"] == 300 * M


def test_defer_options_rank_by_relief_and_by_known_fee():
    invoices = [inv(due=date(2026, 11, 17), amount=100 * M)]       # 100 arrives in week 2
    outgoings = [out("manual:1", 30 * M, AS_OF, fee=2.0, source="manual"), out("bill:1", 30 * M, AS_OF), out("bill:2", 5 * M, AS_OF)]
    result = whatif.defer_options(invoices, ON_TIME, outgoings, AS_OF, defer_days=7)
    assert result["base"]["total_gap"] == 65 * M
    top = result["most_relief"]
    assert {top[0]["outgoing"], top[1]["outgoing"]} == {"manual:1", "bill:1"} and top[0]["gap_reduction"] == 30 * M
    assert top[-1]["outgoing"] == "bill:2" and top[-1]["gap_reduction"] == 5 * M
    fee = result["lowest_known_fee"]
    assert [r["outgoing"] for r in fee] == ["manual:1"] and fee[0]["estimated_fee"] == round(30 * M * 2 / 100 * 7 / 30)
    assert result["helpful_without_fee_info"] == 2                    # bill:1 and bill:2 have no fee information


def test_unknown_fees_are_never_invented():
    result = whatif.defer_options([inv(due=date(2026, 11, 17))], ON_TIME, [out(amount=80 * M)], AS_OF, defer_days=7)
    row = result["most_relief"][0]
    assert row["fee_known"] is False and row["estimated_fee"] is None and result["lowest_known_fee"] == []


def test_outgoings_outside_the_window_are_not_listed():
    far = out("bill:9", 10 * M, date(2027, 6, 1))
    assert whatif.defer_options([inv()], ON_TIME, [far], AS_OF, 7)["outgoings_checked"] == 0


def test_outgoings_are_built_from_odoo_bills_and_typed_expenses():
    manual = [{"id": 5, "description": "Tien thue", "amount": 30 * M, "due_date": "2026-11-12", "late_fee_percent_per_month": 1.5}]
    items = whatif.outgoings_from([(date(2026, 11, 20), 7 * M), (date(2026, 11, 10), 5 * M)], manual)
    assert [o.key for o in items] == ["bill:1", "bill:2", "manual:5"]          # bills are numbered in due-date order
    assert items[0].amount == 5 * M and items[2].fee_pct_per_month == 1.5 and items[0].fee_pct_per_month is None


def test_an_empty_scenario_changes_nothing():
    invoices = [inv(due=AS_OF)]
    base = whatif.run_forecast(invoices, ON_TIME, [out()], AS_OF)
    same = whatif.run_forecast(invoices, ON_TIME, [out()], AS_OF, Scenario())
    assert whatif.compare(base, same)["changed_weeks"] == [] and Scenario().is_empty()
