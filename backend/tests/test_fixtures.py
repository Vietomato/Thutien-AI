import json
from datetime import date
from pathlib import Path
from app.contracts import Invoice, Payment

FIX = Path(__file__).resolve().parents[2] / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_fixtures_match_contract():
    [Invoice(**x) for x in load("invoices.json")]
    [Payment(**x) for x in load("payments.json")]


def test_partial_payment_keeps_remaining_only():
    partial = [i for i in load("invoices.json") if 0 < i["remaining_amount"] < i["invoice_amount"]]
    assert len(partial) == 1 and partial[0]["remaining_amount"] == 60_000_000


def test_c002_delay_series_for_baseline():
    inv = {i["invoice_id"]: i for i in load("invoices.json")}
    delays = sorted(
        (date.fromisoformat(p["payment_date"]) - date.fromisoformat(inv[p["invoice_id"]]["due_date"])).days
        for p in load("payments.json") if p["customer_id"] == "C002")
    assert delays == [-2, 0, 1, 3, 5, 8, 12, 20, 35]