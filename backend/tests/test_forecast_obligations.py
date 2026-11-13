"""F4: expected outgoings typed in by the accountant, added to the Odoo supplier bills in the forecast."""
from datetime import date

import pytest

from app import analytics, audit, obligations
from app.contracts import Invoice, Prediction

AS_OF = date(2026, 11, 9)
M = 1_000_000


def body(**over):
    return {"description": "Tien thue van phong", "amount": 50 * M, "due_date": "2026-11-12", **over}


# ---- entering outgoings -----------------------------------------------------------------

@pytest.mark.parametrize("user", ["acc1", "chief1"])
def test_accountant_and_chief_can_add_an_outgoing(client, team, auth, user):
    r = client.post("/api/obligations", json=body(), headers=auth(user))
    assert r.status_code == 201
    assert r.json()["amount"] == 50 * M and r.json()["created_by_username"] == user
    assert [o["description"] for o in obligations.list_all()] == ["Tien thue van phong"]


@pytest.mark.parametrize("user", ["cust1", "admin1"])
def test_customer_and_admin_cannot_use_outgoings(client, team, auth, user):
    assert client.post("/api/obligations", json=body(), headers=auth(user)).status_code == 403
    assert client.get("/api/obligations", headers=auth(user)).status_code == 403
    assert obligations.list_all() == []


def test_a_token_is_required(client, team):
    assert client.get("/api/obligations").status_code == 401
    assert client.post("/api/obligations", json=body()).status_code == 401


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -5}, {"amount": "abc"}, {"amount": 1.5},
    {"description": ""}, {"description": "x" * 201},
    {"due_date": "not-a-date"}, {"due_date": "2026-13-45"}, {"currency": "USD"},
])
def test_invalid_outgoings_are_rejected_and_not_saved(client, team, auth, bad):
    assert client.post("/api/obligations", json=body(**bad), headers=auth("acc1")).status_code == 422
    assert obligations.list_all() == []


@pytest.mark.parametrize("missing", ["description", "amount", "due_date"])
def test_missing_fields_are_rejected(client, team, auth, missing):
    payload = body()
    del payload[missing]
    assert client.post("/api/obligations", json=payload, headers=auth("acc1")).status_code == 422


def test_adding_an_outgoing_is_written_to_the_audit_log(client, team, auth):
    new_id = client.post("/api/obligations", json=body(), headers=auth("acc1")).json()["id"]
    entry = next(e for e in audit.list_audit() if e["action"] == "obligation_created")
    assert entry["actor"] == "acc1" and entry["target"] == f"obligation:{new_id}"


def test_the_list_is_sorted_by_date_and_marked_manual(client, team, auth):
    client.post("/api/obligations", json=body(description="Luong", due_date="2026-11-25"), headers=auth("acc1"))
    client.post("/api/obligations", json=body(), headers=auth("acc1"))
    out = client.get("/api/obligations", headers=auth("acc1")).json()
    assert out["origin"] == "manual" and [i["description"] for i in out["items"]] == ["Tien thue van phong", "Luong"]


def test_the_database_itself_refuses_a_non_positive_amount(clean_db, team):
    with pytest.raises(Exception):
        obligations.create("x", 0, date(2026, 11, 12), team["acc1"]["id"])


# ---- the forecast uses both sources -----------------------------------------------------

def test_forecast_adds_typed_outgoings_to_the_odoo_supplier_bills(client, team, auth, fake_odoo):
    before = client.get("/api/forecast", headers=auth("acc1")).json()
    client.post("/api/obligations", json=body(amount=50 * M, due_date="2026-11-12"), headers=auth("acc1"))
    after = client.get("/api/forecast", headers=auth("acc1")).json()
    assert after["weeks"][0]["obligations"] == before["weeks"][0]["obligations"] + 50 * M
    assert after["obligations_sources"]["odoo_supplier_bills"] == 500 * M       # the Odoo bill from the fixture
    assert after["obligations_sources"]["manual"] == 50 * M and after["obligations_sources"]["manual_count"] == 1


def test_a_big_typed_outgoing_raises_an_alert_with_the_exact_gap(client, team, auth, fake_odoo):
    fake_odoo["bills"] = []                                              # only the typed outgoing counts here
    week1 = client.get("/api/forecast", headers=auth("acc1")).json()["weeks"][0]["receipt_p75"]
    spend = week1 + 30 * M
    client.post("/api/obligations", json=body(amount=spend, due_date="2026-11-11"), headers=auth("acc1"))
    out = client.get("/api/forecast", headers=auth("acc1")).json()
    assert out["alerts"][0] == {"week_start": "2026-11-09", "receipt_p75": week1, "obligations": spend, "gap_p75": 30 * M}
    assert out["risky_weeks"] == len(out["alerts"])


def test_forecast_reports_the_money_beyond_the_last_week(client, team, auth, fake_odoo):
    out = client.get("/api/forecast", headers=auth("acc1")).json()
    assert set(out["receipts_out_of_horizon"]) == {"p25", "p50", "p75"}
    assert out["obligations_out_of_horizon"] == 0
    client.post("/api/obligations", json=body(amount=7 * M, due_date="2027-09-01"), headers=auth("acc1"))
    assert client.get("/api/forecast", headers=auth("acc1")).json()["obligations_out_of_horizon"] == 7 * M


# ---- analytics: five paid invoices, and money beyond the horizon ------------------------

def inv(inv_id="A", due=date(2026, 11, 20), amount=100):
    return Invoice(invoice_id=inv_id, customer_id="C1", display_name="C1", due_date=due, invoice_amount=amount,
                   remaining_amount=amount)


def test_a_customer_needs_five_paid_invoices_for_their_own_numbers():
    four = analytics.predict_invoice(inv(), AS_OF, [1, 2, 3, 4], [10, 20, 30, 40, 50])
    five = analytics.predict_invoice(inv(), AS_OF, [1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
    assert four.method == "global_median" and four.low_history
    assert five.method == "customer_median" and not five.low_history


def test_reference_series_gives_p25_1_p50_5_p75_12():
    p = analytics.predict_invoice(inv(due=date(2026, 11, 20)), AS_OF, [-2, 0, 1, 3, 5, 8, 12, 20, 35], [])
    assert (p.predicted_date_p25, p.predicted_date_p50, p.predicted_date_p75) == (
        date(2026, 11, 21), date(2026, 11, 25), date(2026, 12, 2))


def _pred(inv_id, p25, p50, p75):
    return Prediction(invoice_id=inv_id, as_of_date=AS_OF, predicted_date_p25=p25, predicted_date_p50=p50,
                      predicted_date_p75=p75, history_count=9, method="customer_median", low_history=False,
                      overdue_adjusted=False)


def test_money_beyond_twelve_weeks_is_reported_and_totals_add_up():
    near = inv("N", amount=30)
    far = inv("F", amount=70)
    preds = [_pred("N", date(2026, 11, 10), date(2026, 11, 12), date(2026, 11, 20)),
             _pred("F", date(2026, 11, 20), date(2027, 3, 1), date(2027, 4, 1))]
    weeks = analytics.forecast([near, far], preds, [], AS_OF)
    beyond = analytics.beyond_horizon([near, far], preds, AS_OF)
    assert beyond == {"p25": 0, "p50": 70, "p75": 70}
    for key in ("p25", "p50", "p75"):
        assert sum(getattr(w, f"receipt_{key}") for w in weeks) + beyond[key] == 100


def test_outgoings_beyond_the_last_week_are_reported():
    bills = [(date(2026, 11, 12), 10), (date(2027, 6, 1), 25)]
    assert analytics.bills_beyond_horizon(bills, AS_OF) == 25


# ---- optional late fee ------------------------------------------------------------------

def test_the_late_fee_is_optional_and_stored_when_given(client, team, auth):
    plain = client.post("/api/obligations", json=body(), headers=auth("acc1")).json()
    fee = client.post("/api/obligations", json=body(description="Tien dien", late_fee_percent_per_month=1.5), headers=auth("acc1")).json()
    assert plain["late_fee_percent_per_month"] is None and fee["late_fee_percent_per_month"] == 1.5
    listed = {o["description"]: o["late_fee_percent_per_month"] for o in client.get("/api/obligations", headers=auth("acc1")).json()["items"]}
    assert listed == {"Tien thue van phong": None, "Tien dien": 1.5}


@pytest.mark.parametrize("bad", [-1, 100.5, "abc"])
def test_a_late_fee_outside_0_to_100_is_refused(client, team, auth, bad):
    assert client.post("/api/obligations", json=body(late_fee_percent_per_month=bad), headers=auth("acc1")).status_code == 422
