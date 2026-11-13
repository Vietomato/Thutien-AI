"""The assistant's tools on a small data set whose numbers were worked out by hand. No database, no network, no LLM.

C1 "Cong ty CP Tong thau Dai Phat": always paid 5 days late (6 invoices).  C2 "Binh Minh": always on time (6 invoices).
C3 "Dai Duong": no open invoices.  As of 2026-11-09 (Monday). Amounts in millions of VND.
  A (C1) 400, due 12/11   -> usual date 17/11 (week 2), expected: 12.5% week 1, 87.5% week 2
  B (C1) 70, disputed     -> no prediction
  C (C2) 200, due 09/11   -> week 1
  D (C2) 50, 10 days overdue, later than any past delay -> counted from today: week 1
  bills: 250 due 10/11; typed expense 100 due 12/11 with a 2%/month fee"""
from datetime import date

import pytest

from app.chat_data import build_snapshot
from app.chat_tools import TOOL_NAMES, TOOL_SPECS, Toolbox, fold, to_date
from app.contracts import Invoice

AS_OF = date(2026, 11, 9)
M = 1_000_000
NAMES = {"C1": "Công ty CP Tổng thầu Đại Phát", "C2": "Công ty TNHH Xây dựng Bình Minh", "C3": "Công ty TNHH Xây dựng Đại Dương"}


def inv(invoice_id, customer, due, amount, dispute="none"):
    return Invoice(invoice_id=invoice_id, customer_id=customer, display_name=NAMES[customer], due_date=due, invoice_amount=amount * M,
                   remaining_amount=amount * M, dispute_status=dispute, contact_email="a@example.com")


@pytest.fixture
def box():
    snap = build_snapshot(
        AS_OF, "odoo", [inv("INV/A", "C1", date(2026, 11, 12), 400), inv("INV/B", "C1", date(2026, 10, 20), 70, "disputed"),
                        inv("INV/C", "C2", date(2026, 11, 9), 200), inv("INV/D", "C2", date(2026, 10, 30), 50)],
        [("C1", 5)] * 6 + [("C2", 0)] * 6, [(date(2026, 11, 10), 250 * M)],
        [{"id": 1, "description": "Tien thue", "amount": 100 * M, "due_date": "2026-11-12", "late_fee_percent_per_month": 2.0}],
        [{"customer_id": cid, "name": name} for cid, name in NAMES.items()], set())
    return Toolbox(snap)


# ---------------------------------------------------------------- finding customers

def test_names_match_without_accents_and_with_a_part_of_the_name(box):
    found = box.call("search_customers", {"query": "dai phat"})["matches"]
    assert found[0]["customer_id"] == "C1" and found[0]["all_words_match"] and found[0]["open_invoices"] == 2
    assert fold("Đại Phát") == "dai phat"


def test_a_part_of_a_name_that_fits_two_customers_is_ambiguous(box):
    result = box.call("get_customer", {"customer": "Đại"})
    assert "2 khách" in result["error"] and {c["customer_id"] for c in result["candidates"]} == {"C1", "C3"}


def test_an_unknown_customer_is_reported_not_guessed(box):
    result = box.call("get_customer", {"customer": "Hoàng Long"})
    assert "error" in result and "hint" in result


def test_a_customer_id_works_too(box):
    assert box.call("get_customer", {"customer": "c2"})["customer_id"] == "C2"


def test_customer_profile(box):
    p = box.call("get_customer", {"customer": "Đại Phát"})
    assert (p["open_invoices"], p["open_amount"], p["overdue_invoices"], p["disputed_invoices"]) == (2, 470 * M, 0, 1)
    h = p["payment_history"]
    assert (h["paid_invoices"], h["share_paid_late"], h["days_late_median"], h["enough_history"]) == (6, 1.0, 5, True)


def test_a_customer_without_open_invoices_has_an_empty_profile(box):
    p = box.call("get_customer", {"customer": "Đại Dương"})
    assert p["open_invoices"] == 0 and p["payment_history"] is None and p["biggest_open_invoices"] == []


# ---------------------------------------------------------------- invoices

def test_overdue_filter_skips_disputed_invoices(box):
    r = box.call("list_invoices", {"status": "overdue"})
    assert r["matching_invoices"] == 1 and r["invoices"][0]["invoice_id"] == "INV/D" and r["invoices"][0]["days_overdue"] == 10


def test_sorting_by_expected_delay_puts_the_slowest_payer_first(box):
    order = [i["invoice_id"] for i in box.call("list_invoices", {"sort_by": "expected_delay", "status": "not_due"})["invoices"]]
    assert order == ["INV/A", "INV/C"]                           # 5 days late against on time
    everything = [i["invoice_id"] for i in box.call("list_invoices", {"sort_by": "expected_delay"})["invoices"]]
    assert everything[0] == "INV/D"                              # 30/10 -> 10/11 = 11 days after its due date


def test_the_prediction_comes_with_its_basis(box):
    a = next(i for i in box.call("list_invoices", {"customer": "Đại Phát"})["invoices"] if i["invoice_id"] == "INV/A")
    assert a["predicted"]["usual"] == "2026-11-17" and a["predicted"]["usual_delay_days_after_due"] == 5
    assert a["predicted"]["paid_invoices_behind_it"] == 6 and "chính khách" in a["predicted"]["basis"]
    b = next(i for i in box.call("list_invoices", {"status": "disputed"})["invoices"])
    assert b["predicted"] is None and b["status"] == "disputed"


def test_amount_filters_and_the_limit(box):
    r = box.call("list_invoices", {"min_amount": 100 * M, "limit": 1, "sort_by": "amount"})
    assert r["matching_invoices"] == 2 and r["shown"] == 1 and r["invoices"][0]["invoice_id"] == "INV/A"


def test_invoice_detail_by_full_code_or_ending(box):
    full = box.call("get_invoice", {"invoice_id": "INV/D"})
    assert full["days_overdue"] == 10 and full["has_pending_draft"] is False and "tỷ lệ trả trễ" in full["score_formula"]
    assert box.call("get_invoice", {"invoice_id": "D"})["invoice_id"] == "INV/D"
    assert "error" in box.call("get_invoice", {"invoice_id": "INV/ZZZ"})


# ---------------------------------------------------------------- forecast

def test_forecast_weeks(box):
    w = box.call("get_forecast", {"from_week": 1, "to_week": 2})["weeks"]
    assert w[0]["receipts_late_scenario"] == 250 * M and w[0]["outgoings"] == 350 * M and w[0]["shortfall_if_customers_pay_late"] == 100 * M
    assert w[0]["receipts_expected"] == 300 * M and w[1]["receipts_expected"] == 350 * M and w[1]["receipts_late_scenario"] == 400 * M
    summary = box.call("get_forecast", {})["summary_all_12_weeks"]
    assert summary["risky_week_numbers"] == [1] and summary["total_gap"] == 100 * M


def test_a_bad_week_range_is_refused(box):
    assert "error" in box.call("get_forecast", {"from_week": 5, "to_week": 2})
    assert "error" in box.call("get_week_detail", {"week": 13})


def test_week_detail_lists_the_invoices_and_the_outgoings(box):
    d = box.call("get_week_detail", {"week": 1})
    assert {i["invoice_id"] for i in d["invoices_behind_expected_receipts"]} == {"INV/A", "INV/C", "INV/D"}
    top = d["invoices_behind_expected_receipts"][0]
    assert top["invoice_id"] == "INV/C" and top["probability"] == 1.0 and top["expected_amount"] == 200 * M
    assert d["outgoings_due_this_week_count"] == 2


def test_overview(box):
    o = box.call("get_overview", {})
    assert o["forecast_12_weeks"]["risky_weeks"] == 1 and o["forecast_12_weeks"]["outgoings"] == 350 * M
    assert o["outgoings_known"] == {"supplier_bills_in_odoo": 1, "typed_by_accountants": 1}


def test_outgoings_say_what_they_do_not_know(box):
    r = box.call("list_outgoings", {})
    by_key = {o["outgoing"]: o for o in r["outgoings"]}
    assert by_key["manual:1"]["late_fee_known"] and by_key["manual:1"]["late_fee_percent_per_month"] == 2.0
    assert by_key["bill:1"]["late_fee_known"] is False and "không có tên nhà cung cấp" in r["note"]
    assert [o["outgoing"] for o in box.call("list_outgoings", {"source": "manual"})["outgoings"]] == ["manual:1"]
    assert "error" in box.call("list_outgoings", {"source": "bank"})


# ---------------------------------------------------------------- scenarios

def test_what_if_a_customer_pays_later(box):
    r = box.call("what_if", {"customer_delays": [{"customer": "Đại Phát", "extra_days": 10}]})
    assert r["affected"][0]["open_invoices_affected"] == 1 and r["affected"][0]["amount_affected"] == 400 * M   # the disputed one is left out
    assert [w["week"] for w in r["changed_weeks"]] == [1, 2, 3]          # week 1 changes too: 12.5% of A was expected there
    week1, week2 = r["changed_weeks"][0], r["changed_weeks"][1]
    assert week1["expected_receipts_before"] == 300 * M and week1["expected_receipts_after"] == 250 * M and week1["late_receipts_after"] == 250 * M
    assert week2["late_receipts_before"] == 400 * M and week2["late_receipts_after"] == 0
    assert r["newly_short_weeks"] == [] and r["scenario"]["total_gap"] == r["base"]["total_gap"] == 100 * M
    assert "chậm thêm 10 ngày" in r["assumptions"][0]


def test_what_if_the_on_time_customer_pays_later_deepens_the_gap(box):
    r = box.call("what_if", {"customer_delays": [{"customer": "Bình Minh", "extra_days": 10}]})
    assert r["base"]["total_gap"] == 100 * M and r["scenario"]["total_gap"] == 350 * M


def test_what_if_numbers_may_arrive_as_text(box):
    r = box.call("what_if", {"customer_delays": [{"customer": "C1", "extra_days": "20"}]})
    assert "error" not in r and "20 ngày" in r["assumptions"][0]


def test_what_if_a_customer_with_nothing_open_changes_nothing_and_says_so(box):
    r = box.call("what_if", {"customer_delays": [{"customer": "Đại Dương", "extra_days": 20}]})
    assert r["changed_weeks"] == [] and any("không có hóa đơn" in n for n in r["notes"])


def test_what_if_everyone_pays_later(box):
    r = box.call("what_if", {"all_customers_extra_days": 14})
    assert r["scenario"]["total_gap"] > r["base"]["total_gap"] and "Tất cả khách hàng" in r["assumptions"][0]


def test_what_if_pay_now_brings_receipts_forward(box):
    r = box.call("what_if", {"customers_pay_now": ["Đại Phát"]})
    assert r["scenario"]["total_gap"] == 0 and r["no_longer_short_weeks"] == [1]


def test_what_if_deferring_a_bill_and_adding_a_payment(box):
    r = box.call("what_if", {"defer": [{"outgoing": "bill:1", "days": 7}], "extra_outgoings": [{"amount": 500 * M, "due_date": "20/11", "label": "may moi"}]})
    # the 250 bill moves to 17/11 and the new 500 lands on 20/11: both in week 2, 750 against 400 received; week 1 is covered now
    assert r["scenario"]["risky_week_numbers"] == [2] and r["scenario"]["total_gap"] == 350 * M
    assert any("may moi" in a for a in r["assumptions"])


def test_what_if_refuses_an_empty_or_invalid_scenario(box):
    assert "error" in box.call("what_if", {})
    assert "bill:1" in box.call("what_if", {"defer": [{"outgoing": "bill:99", "days": 3}]})["hint"]
    assert "extra_days" in box.call("what_if", {"customer_delays": [{"customer": "C1", "extra_days": "abc"}]})["error"]
    assert "error" in box.call("what_if", {"extra_outgoings": [{"amount": 10, "due_date": "not a date"}]})
    assert "error" in box.call("what_if", {"customer_delays": [{"customer": "Hoàng Long", "extra_days": 5}]})


def test_defer_options_with_and_without_fee_information(box):
    r = box.call("defer_options", {"defer_days": 7})
    relief = {o["outgoing"]: o for o in r["most_relief"]}
    assert set(relief) == {"bill:1", "manual:1"} and all(o["gap_reduction"] == 100 * M for o in relief.values())
    assert [o["outgoing"] for o in r["lowest_known_fee"]] == ["manual:1"] and r["lowest_known_fee"][0]["estimated_fee"] == 466_667
    assert relief["bill:1"]["fee_known"] is False and r["helpful_without_fee_info"] == 1 and "không có điều khoản phạt" in r["note"]


def test_a_longer_deferral_can_make_things_worse_and_is_not_offered_as_relief(box):
    r = box.call("defer_options", {"defer_days": 14})
    assert r["most_relief"] == [] and r["helpful_count"] == 0


# ---------------------------------------------------------------- the rest

def test_method_explanations_are_fixed_text_with_the_real_constants(box):
    r = box.call("explain_method", {"topic": "prediction"})
    assert "P25, P50, P75" in r["explanation"] and r["constants"]["min_paid_invoices_for_own_history"] == 5
    assert "error" in box.call("explain_method", {"topic": "weather"})


def test_unknown_tools_and_bad_arguments_return_errors_instead_of_raising(box):
    assert "error" in box.call("delete_everything", {})
    assert "error" in box.call("get_forecast", {"from_week": "x"})
    assert box.call("get_overview", None)["as_of"] == "2026-11-09"


def test_every_tool_the_model_is_shown_exists_and_has_a_schema():
    assert TOOL_NAMES == {t["name"] for t in TOOL_SPECS} and len(TOOL_SPECS) == 11
    for spec in TOOL_SPECS:
        assert callable(getattr(Toolbox, spec["name"])) and spec["parameters"]["type"] == "object" and spec["description"]


def test_dates_are_read_in_the_formats_people_write():
    assert to_date("2026-12-05", "d", AS_OF) == date(2026, 12, 5)
    assert to_date("05/12/2026", "d", AS_OF) == date(2026, 12, 5)
    assert to_date("5/12", "d", AS_OF) == date(2026, 12, 5)
    assert to_date("1/2", "d", AS_OF) == date(2027, 2, 1)           # a date long past this year means next year
