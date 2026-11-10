"""Pure logic: no database, no network."""
from datetime import date

import pytest

from app import analytics
from app.contracts import Invoice
from app.permissions import ADMIN, CHIEF, CUSTOMER, ACCOUNTANT, ROLES, has_permission, permissions_of
from app.security import hash_password, verify_password

AS_OF = date(2026, 11, 9)


def inv(invoice_id="I1", customer="C1", due=date(2026, 10, 10), amount=100, remaining=None, dispute="none"):
    return Invoice(invoice_id=invoice_id, customer_id=customer, display_name="X", due_date=due,
                   invoice_amount=amount, remaining_amount=amount if remaining is None else remaining,
                   dispute_status=dispute)


# ---------- passwords ----------

def test_password_roundtrip_and_salt():
    h = hash_password("Correct-horse1")
    assert verify_password("Correct-horse1", h)
    assert not verify_password("wrong", h)
    assert h != hash_password("Correct-horse1")  # random salt
    assert "Correct-horse1" not in h


def test_garbage_hash_never_verifies():
    assert not verify_password("x", "")
    assert not verify_password("x", "plaintext")
    assert not verify_password("x", "scrypt$a$b$c$d$e")


# ---------- permission matrix ----------

def test_every_role_is_defined():
    assert set(ROLES) == {ACCOUNTANT, CHIEF, CUSTOMER, ADMIN}
    for r in ROLES:
        assert permissions_of(r)


def test_only_chief_can_decide_and_assign():
    assert has_permission(CHIEF, "draft:decide") and has_permission(CHIEF, "task:assign")
    for r in (ACCOUNTANT, CUSTOMER, ADMIN):
        assert not has_permission(r, "draft:decide")
        assert not has_permission(r, "task:assign")


def test_chief_includes_everything_an_accountant_can_do():
    assert permissions_of(ACCOUNTANT) <= permissions_of(CHIEF)


def test_customer_has_no_staff_data():
    for p in ("invoice:read_all", "payment:read_all", "prediction:read", "forecast:read", "draft:create", "user:manage"):
        assert not has_permission(CUSTOMER, p)
    assert has_permission(CUSTOMER, "invoice:read_own")


def test_admin_has_no_financial_permission():
    financial = [p for p in permissions_of(ADMIN) if p.split(":")[0] in {"invoice", "payment", "summary", "prediction", "forecast", "draft", "task"}]
    assert financial == []
    assert has_permission(ADMIN, "user:manage") and has_permission(ADMIN, "audit:read")


def test_unknown_role_has_nothing():
    assert permissions_of("hacker") == frozenset()


# ---------- analytics ----------

def test_percentile_interpolates():
    assert analytics.percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert analytics.percentile([0, 10], 0.25) == 2.5
    assert analytics.percentile([7], 0.75) == 7


def test_customer_history_drives_prediction():
    p = analytics.predict_invoice(inv(due=date(2026, 11, 20)), AS_OF, [0, 2, 4, 6, 8], [])
    assert p.method == "customer_median" and not p.low_history and p.history_count == 5
    assert (p.predicted_date_p25, p.predicted_date_p50, p.predicted_date_p75) == (
        date(2026, 11, 22), date(2026, 11, 24), date(2026, 11, 26))


def test_thin_history_falls_back_to_everyone():
    p = analytics.predict_invoice(inv(due=date(2026, 11, 20)), AS_OF, [5], [1, 2, 3, 4, 5, 6])
    assert p.method == "global_median" and p.low_history


def test_no_history_at_all():
    p = analytics.predict_invoice(inv(due=date(2026, 11, 20)), AS_OF, [], [])
    assert p.method == "no_history" and p.low_history
    assert p.predicted_date_p50 == date(2026, 11, 20)


def test_disputed_invoice_gets_no_prediction():
    assert analytics.predict_invoice(inv(dispute="disputed"), AS_OF, [1, 2, 3], [1, 2, 3]) is None


def test_overdue_uses_only_delays_at_least_as_long():
    # 30 days overdue: only the delays 30 and 40 are still possible.
    p = analytics.predict_invoice(inv(due=date(2026, 10, 10)), AS_OF, [2, 5, 7, 30, 40], [])
    assert not p.overdue_adjusted
    assert p.predicted_date_p25 >= AS_OF


def test_overdue_longer_than_all_history_is_shifted_from_today():
    p = analytics.predict_invoice(inv(due=date(2026, 9, 1)), AS_OF, [2, 4, 6, 8, 10], [])
    assert p.overdue_adjusted
    assert p.predicted_date_p25 > AS_OF  # never in the past


def test_predictions_are_ordered_and_never_in_the_past():
    for due in (date(2026, 8, 1), date(2026, 11, 1), date(2026, 12, 25)):
        p = analytics.predict_invoice(inv(due=due), AS_OF, [-2, 0, 1, 3, 5, 8, 12, 20, 35], [])
        assert AS_OF <= p.predicted_date_p25 <= p.predicted_date_p50 <= p.predicted_date_p75


def test_forecast_buckets_receipts_and_flags_gaps():
    invoices = [inv("A", amount=100, due=date(2026, 11, 20)), inv("B", amount=50, due=date(2026, 11, 20))]
    preds = analytics.predict(invoices, [("C1", 0)] * 5, AS_OF)
    bills = [(date(2026, 11, 10), 80), (date(2026, 10, 1), 20)]  # second bill is already overdue -> week 1
    weeks = analytics.forecast(invoices, preds, bills, AS_OF)
    assert len(weeks) == 12 and weeks[0].week_start == AS_OF
    assert weeks[0].obligations == 100                       # both bills land in week 1
    assert sum(w.receipt_p50 for w in weeks) == 150          # every invoice is counted exactly once
    assert weeks[0].gap_p75 == 100                            # nothing arrives in week 1, so the full 100 is short
    assert weeks[1].receipt_p50 == 150 and weeks[1].gap_p75 == 0   # 20/11 is 11 days out: second week


def test_forecast_ignores_disputed_and_far_future():
    invoices = [inv("A", amount=100, due=date(2027, 6, 1)), inv("B", amount=70, dispute="disputed")]
    preds = analytics.predict(invoices, [("C1", 0)] * 5, AS_OF)
    weeks = analytics.forecast(invoices, preds, [], AS_OF)
    assert sum(w.receipt_p50 for w in weeks) == 0


def test_summary_numbers():
    s = analytics.summarize([
        inv("A", due=date(2026, 10, 10), amount=120),
        inv("B", due=date(2026, 10, 20), amount=70, dispute="disputed"),
        inv("C", due=date(2026, 11, 24), amount=40),
        inv("D", due=date(2026, 11, 2), amount=90, remaining=60),
    ], AS_OF)
    assert s["total_remaining"] == 290 and s["open_count"] == 4
    assert s["overdue_amount"] == 250 and s["overdue_count"] == 3
    assert (s["min_overdue_days"], s["max_overdue_days"]) == (7, 30)
    assert s["disputed_amount"] == 70 and s["disputed_count"] == 1


def test_summary_of_nothing():
    s = analytics.summarize([], AS_OF)
    assert s["total_remaining"] == 0 and s["max_overdue_days"] == 0
