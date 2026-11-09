from datetime import date
from decimal import Decimal

from app.contracts import Invoice
from app.f3_priority import rank_priority
from app import odoo_reader

AS_OF = date(2026, 11, 9)


def invoice(invoice_id, customer, remaining, due, *, total=None, dispute="none", email="ar@example.test"):
    return Invoice(
        invoice_id=invoice_id,
        customer_id=customer,
        display_name=customer,
        due_date=due,
        invoice_amount=total if total is not None else remaining,
        remaining_amount=remaining,
        dispute_status=dispute,
        contact_email=email,
    )


def test_priority_matches_contract_example_and_tie_breaks():
    rows = rank_priority(
        [
            invoice("B", "B", 30_000_000, date(2026, 11, 7)),
            invoice("A", "A", 80_000_000, date(2026, 11, 5)),
        ],
        [("A", 1), ("A", -1), ("B", 2)],
        as_of_date=AS_OF,
        predictions=[],
        active_draft_invoice_ids=set(),
    )
    assert [row["invoice_id"] for row in rows] == ["A", "B"]
    assert Decimal(rows[0]["priority_score"]) == Decimal("160000000")
    assert Decimal(rows[1]["priority_score"]) == Decimal("60000000")


def test_customer_global_and_no_history_fallbacks_are_labeled():
    rows = rank_priority(
        [invoice("C", "C", 100, date(2026, 11, 8)), invoice("D", "D", 100, date(2026, 11, 8))],
        [("A", 3), ("A", -1)],
        as_of_date=AS_OF,
        predictions=[],
        active_draft_invoice_ids=set(),
    )
    by_id = {row["invoice_id"]: row for row in rows}
    assert by_id["C"]["late_rate_source"] == "global_history"
    assert by_id["C"]["late_rate"] == "0.5"
    assert by_id["D"]["priority_score"] == "50.0"

    no_history = rank_priority(
        [invoice("E", "E", 100, date(2026, 11, 8))],
        [],
        as_of_date=AS_OF,
        predictions=[],
        active_draft_invoice_ids=set(),
    )[0]
    assert no_history["late_rate_source"] == "assumed_0.5_no_history"


def test_held_reminder_reasons_and_remaining_balance():
    rows = rank_priority(
        [
            invoice("partial", "A", 80, date(2026, 11, 5), total=100),
            invoice("disputed", "A", 80, date(2026, 11, 5), dispute="disputed"),
            invoice("no-email", "A", 80, date(2026, 11, 5), email=" "),
            invoice("draft", "A", 80, date(2026, 11, 5)),
            invoice("not-due", "A", 80, date(2026, 11, 10)),
        ],
        [],
        as_of_date=AS_OF,
        predictions=[],
        active_draft_invoice_ids={"draft"},
    )
    by_id = {row["invoice_id"]: row for row in rows}
    assert by_id["partial"]["eligible_for_reminder"] is True
    assert by_id["partial"]["priority_score"] == "160.0"
    assert by_id["disputed"]["hold_reasons"] == ["disputed"]
    assert by_id["no-email"]["hold_reasons"] == ["missing_contact"]
    assert by_id["draft"]["hold_reasons"] == ["active_draft_exists"]
    assert by_id["not-due"]["hold_reasons"] == ["not_overdue"]


def test_paid_delay_history_is_cut_off_at_as_of_date(monkeypatch):
    calls = {}

    def fake_query(sql, params):
        calls["sql"] = sql
        calls["params"] = params
        return [("C001", 4)]

    monkeypatch.setattr(odoo_reader, "_query", fake_query)
    assert odoo_reader.paid_delays(AS_OF) == [("C001", 4)]
    assert "max(pr.max_date)::date - m.invoice_date_due" in calls["sql"]
    assert "HAVING max(pr.max_date)::date <= %s" in calls["sql"]
    assert calls["params"] == [AS_OF]


def test_f3_api_returns_ranked_live_contract_shape_with_fake_readers(monkeypatch):
    from fastapi.testclient import TestClient

    from app import drafts
    from app.auth import current_user
    from app.main import app

    inv = invoice("INV-1", "C-1", 30_000_000, date(2026, 11, 7))
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: {"role": "accountant", "username": "test"})
    monkeypatch.setattr(odoo_reader, "open_invoices", lambda customer_id=None: [inv])
    monkeypatch.setattr(odoo_reader, "paid_delays", lambda as_of_date=None: [])
    monkeypatch.setattr(drafts, "pending_invoice_ids", lambda: set())

    response = TestClient(app).get("/api/f3/priority")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "odoo"
    assert payload["items"][0]["invoice_id"] == "INV-1"
    assert payload["items"][0]["priority_score"] == "30000000.0"
    assert payload["items"][0]["prediction"]["method"] == "no_history"
