import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.contracts import Invoice, Payment

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "demo_company"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_fixtures_match_contract():
    [Invoice(**x) for x in load("invoices.json")]
    [Payment(**x) for x in load("payments.json")]


def test_ids_are_unique_and_every_payment_has_an_invoice():
    invoices, payments = load("invoices.json"), load("payments.json")
    invoice_ids = {i["invoice_id"] for i in invoices}
    assert len(invoice_ids) == len(invoices)
    assert len({p["payment_id"] for p in payments}) == len(payments)
    assert all(p["invoice_id"] in invoice_ids for p in payments)


def test_remaining_amount_is_invoice_amount_minus_payments():
    """A partially paid invoice keeps only what is still owed; nothing is double counted."""
    paid = defaultdict(int)
    for p in load("payments.json"):
        paid[p["invoice_id"]] += p["amount"]
    invoices = load("invoices.json")
    assert all(i["remaining_amount"] == i["invoice_amount"] - paid[i["invoice_id"]] for i in invoices)
    assert any(0 < i["remaining_amount"] < i["invoice_amount"] for i in invoices)


def test_payment_delays_can_be_computed_for_every_paid_customer():
    """The baseline needs (payment date - due date) per customer; both a late and an early payer must exist."""
    invoices = {i["invoice_id"]: i for i in load("invoices.json")}
    delays = [
        (date.fromisoformat(p["payment_date"]) - date.fromisoformat(invoices[p["invoice_id"]]["due_date"])).days
        for p in load("payments.json") if invoices[p["invoice_id"]]["due_date"]
    ]
    assert delays and min(delays) < 0 < max(delays)
