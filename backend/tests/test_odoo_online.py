"""Cloud reader tests use a fake JSON-2 transport; no Odoo.com account is needed."""
from datetime import date
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app import odoo_online, odoo_reader


@pytest.fixture(autouse=True)
def online_env(monkeypatch):
    monkeypatch.setenv("ODOO_ONLINE_URL", "https://demo-trading-company.odoo.com")
    monkeypatch.setenv("ODOO_ONLINE_API_KEY", "very-private-test-key")
    monkeypatch.delenv("ODOO_ONLINE_DISPUTE_FIELD", raising=False)
    odoo_online._CACHE.clear()
    yield
    odoo_online._CACHE.clear()


def test_requires_https_origin_and_api_key(monkeypatch):
    monkeypatch.setenv("ODOO_ONLINE_URL", "http://example.com")
    with pytest.raises(odoo_online.OdooOnlineError, match="HTTPS"):
        odoo_online.open_invoices()
    monkeypatch.setenv("ODOO_ONLINE_URL", "https://demo-trading-company.odoo.com")
    monkeypatch.delenv("ODOO_ONLINE_API_KEY")
    with pytest.raises(odoo_online.OdooOnlineError, match="API_KEY"):
        odoo_online.open_invoices()


@pytest.mark.parametrize("status,expected", [(401, "rejected the API key"), (403, "Custom plan")])
def test_http_error_does_not_disclose_key_or_odoo_response(monkeypatch, status, expected):
    def denied(request, timeout):
        raise HTTPError(request.full_url, status, "denied", {}, BytesIO(b"very-private-test-key"))

    monkeypatch.setattr(odoo_online, "urlopen", denied)
    with pytest.raises(odoo_online.OdooOnlineError) as exc:
        odoo_online._call("account.move", "search_read", domain=[], fields=[])
    assert "very-private-test-key" not in str(exc.value)
    assert f"HTTP {status}" in str(exc.value)
    assert expected in str(exc.value)


def test_open_invoices_map_odoo_name_partner_and_version(monkeypatch):
    moves = [
        {"id": 10, "name": "INV/2026/001", "ref": False, "partner_id": [7, "Khách A"],
         "invoice_date_due": "2026-10-10", "amount_total": 1000000, "amount_residual": 500000,
         "currency_id": [2, "VND"], "narration": "[DISPUTE]", "write_date": "2026-11-09 09:00:00"},
        {"id": 11, "name": "INV/2026/002", "ref": False, "partner_id": [8, "Client B"],
         "invoice_date_due": "2026-10-11", "amount_total": 200, "amount_residual": 200,
         "currency_id": [3, "USD"], "narration": False, "write_date": "2026-11-09 10:00:00"},
    ]

    def search(model, domain, fields):
        if model == "account.move":
            return moves
        if model == "res.partner":
            return [{"id": 7, "name": "Khách A", "ref": "C007", "email": "a@example.test"},
                    {"id": 8, "name": "Client B", "ref": False, "email": False}]
        if model == "res.currency":
            return [{"id": 2, "name": "VND"}, {"id": 3, "name": "USD"}]
        raise AssertionError(model)

    monkeypatch.setattr(odoo_online, "_search_read", search)
    all_invoices = odoo_online.open_invoices()
    assert len(all_invoices) == 1
    inv = all_invoices[0]
    assert (inv.invoice_id, inv.customer_id, inv.remaining_amount) == ("INV/2026/001", "C007", 500000)
    assert inv.dispute_status == "disputed" and inv.contact_email == "a@example.test"
    assert inv.source_version == "2026-11-09 09:00:00"
    assert odoo_online.open_invoices("C007") == all_invoices
    assert odoo_online.open_invoices("C008") == []


def test_single_invoice_rereads_cloud_instead_of_using_list_cache(monkeypatch):
    state = {"version": "v1"}

    def search(model, domain, fields):
        if model == "account.move":
            return [{"id": 10, "name": "INV/2026/001", "ref": False, "partner_id": [7, "Khách A"],
                     "invoice_date_due": "2026-10-10", "amount_total": 100, "amount_residual": 50,
                     "currency_id": [2, "VND"], "narration": False, "write_date": state["version"]}]
        if model == "res.partner":
            return [{"id": 7, "name": "Khách A", "ref": "C007", "email": "a@example.test"}]
        if model == "res.currency":
            return [{"id": 2, "name": "VND"}]
        raise AssertionError(model)

    monkeypatch.setattr(odoo_online, "_search_read", search)
    assert odoo_online.open_invoices()[0].source_version == "v1"
    state["version"] = "v2"
    assert odoo_online.open_invoice("INV/2026/001").source_version == "v2"
    assert odoo_online.open_invoices()[0].source_version == "v1"


def test_payment_history_and_paid_delays_use_only_fully_paid_invoices(monkeypatch):
    def search(model, domain, fields):
        if model == "account.partial.reconcile":
            return [{"id": 1, "debit_move_id": [101, "line"], "max_date": "2026-10-20", "amount": 100},
                    {"id": 2, "debit_move_id": [102, "line"], "max_date": "2026-10-22", "amount": 20}]
        if model == "account.move.line":
            return [{"id": 101, "move_id": [10, "invoice"]}, {"id": 102, "move_id": [11, "invoice"]}]
        if model == "account.move":
            return [{"id": 10, "name": "INV-1", "ref": False, "partner_id": [7, "A"],
                     "invoice_date_due": "2026-10-10", "amount_residual": 0, "currency_id": [2, "VND"]},
                    {"id": 11, "name": "INV-2", "ref": False, "partner_id": [7, "A"],
                     "invoice_date_due": "2026-10-12", "amount_residual": 80, "currency_id": [2, "VND"]}]
        if model == "res.partner":
            return [{"id": 7, "name": "A", "ref": "C007", "email": "a@example.test"}]
        if model == "res.currency":
            return [{"id": 2, "name": "VND"}]
        raise AssertionError(model)

    monkeypatch.setattr(odoo_online, "_search_read", search)
    assert len(odoo_online.payment_history("C007")) == 2
    assert odoo_online.paid_delays(date(2026, 10, 19)) == []
    assert odoo_online.paid_delays(date(2026, 10, 21)) == [("C007", 10)]


def test_reader_dispatches_to_online_without_touching_postgres(monkeypatch):
    monkeypatch.setenv("ODOO_SOURCE", "online")
    monkeypatch.setattr(odoo_online, "open_invoices", lambda customer_id=None: [])
    monkeypatch.setattr(odoo_reader, "_connect", lambda: (_ for _ in ()).throw(AssertionError("local DB used")))
    assert odoo_reader.open_invoices() == []
