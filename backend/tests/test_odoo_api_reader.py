"""Odoo API reader, tested against a fake Odoo (no network, no real instance).

Every test runs twice, once per transport (json2 and xmlrpc), against the same fake data."""
import json
import types
import xmlrpc.client
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import odoo_api_reader as reader, odoo_reader, sources
from app.main import app

KEY = "SECRET-API-KEY-123"
FIRST_ARG = {"search_read": "domain", "search_count": "domain", "read": "ids"}


class FakeOdoo:
    """Answers like Odoo does: many2one as [id, name], False for empty fields. One data model, two transports."""

    def __init__(self, partners, moves, lines, reconciles):
        self.tables = {"res.partner": partners, "account.move": moves,
                       "account.move.line": lines, "account.partial.reconcile": reconciles}
        self.calls = []          # (model, method, params), params as JSON would carry them
        self.urls = []
        self.headers = []
        self.auth_ok = True
        self.denied = False      # authenticated, but the user may not read the data
        self.server_error = None
        self.down = False
        self.transport = None

    # ---- the data model, shared by both transports
    def _run(self, model, method, params):
        params = json.loads(json.dumps(params))
        self.calls.append((model, method, params))
        rows = self.tables[model]
        if method == "search_read":
            if ["amount_residual", ">", 0] in params["domain"]:
                rows = [r for r in rows if r["amount_residual"] > 0]
            rows = sorted(rows, key=lambda r: r["id"])[params["offset"]: params["offset"] + params["limit"]]
        elif method == "read":
            rows = [r for r in rows if r["id"] in params["ids"]]
        else:
            raise AssertionError(f"unexpected method {method}")
        return [{f: r[f] for f in ["id", *params["fields"]] if f in r} for r in rows]

    # ---- json2
    def http_post(self, url, headers, body):
        self.urls.append(url)
        self.headers.append(headers)
        if self.down:
            raise ConnectionRefusedError("connection refused")
        if not self.auth_ok:
            return 401, json.dumps({"message": "Invalid apikey"})
        if self.denied:
            return 403, json.dumps({"message": "You are not allowed to access 'Journal Entry' (account.move) records.\n"
                                                "\tThis operation is allowed for: Accounting / Invoicing"})
        if self.server_error:
            return 500, json.dumps({"message": self.server_error})
        model, method = url.partition("/json/2/")[2].rsplit("/", 1)
        return 200, json.dumps(self._run(model, method, json.loads(body)))

    # ---- xmlrpc
    def proxy(self, url, path):
        self.urls.append(f"{url}/xmlrpc/2/{path}")
        if path == "common":
            return types.SimpleNamespace(authenticate=self._x_auth)
        return types.SimpleNamespace(execute_kw=self._x_exec)

    def _x_auth(self, db, user, key, ctx):
        if self.down:
            raise ConnectionRefusedError("connection refused")
        return 7 if self.auth_ok else False

    def _x_exec(self, db, uid, key, model, method, args, kwargs):
        if self.down:
            raise ConnectionRefusedError("connection refused")
        if self.denied:
            raise xmlrpc.client.Fault(2, "You are not allowed to access 'Journal Entry'. Accounting / Invoicing")
        if self.server_error:
            raise xmlrpc.client.Fault(1, self.server_error)
        return self._run(model, method, {FIRST_ARG[method]: args[0], **kwargs})


def partner(pid, ref, name, email):
    return {"id": pid, "ref": ref, "name": name, "email": email}


def move(mid, ref, pid, due, total, residual, invoice_date=False, narration=False):
    return {"id": mid, "ref": ref, "partner_id": [pid, "x"] if pid else False, "invoice_date_due": due,
            "invoice_date": invoice_date, "amount_total": total, "amount_residual": residual, "narration": narration}


@pytest.fixture(params=["json2", "xmlrpc"])
def odoo(request, monkeypatch):
    partners = [partner(1, "C100", "Khach A", "a@example.test"), partner(2, False, "Khach B", False)]
    moves = [
        move(10, "INV-10", 1, "2026-10-01", 100.0, 0.0),                        # paid
        move(11, "INV-11", 1, "2026-10-20", 250.4, 250.4),                      # open, amounts rounded
        move(12, False, 2, False, 80.0, 80.0, invoice_date="2026-10-05"),       # no ref, due falls back to invoice date
        move(13, "INV-13", 1, "2026-10-25", 60.0, 60.0, narration="<p>[DISPUTE] sai gia</p>"),
        move(14, "INV-14", 2, False, 40.0, 40.0),                               # no due date at all: skipped
        move(15, "INV-15", False, "2026-10-30", 40.0, 40.0),                    # no customer: skipped
    ]
    lines = [{"id": 100, "move_id": [10, "INV-10"]}, {"id": 101, "move_id": [12, "x"]}]
    recs = [{"id": 900, "debit_move_id": [100, "l"], "amount": 100.0, "max_date": "2026-10-03"},
            {"id": 901, "debit_move_id": [101, "l"], "amount": 30.0, "max_date": "2026-10-12"},
            {"id": 902, "debit_move_id": [101, "l"], "amount": 10.0, "max_date": False}]     # no date: skipped
    fake = FakeOdoo(partners, moves, lines, recs)
    fake.transport = request.param
    monkeypatch.setattr(reader, "_proxy", fake.proxy)
    monkeypatch.setattr(reader, "_http_post", fake.http_post)
    monkeypatch.setenv("ODOO_API_TRANSPORT", request.param)
    for name, value in (("ODOO_URL", "https://demo.odoo.com/"), ("ODOO_DB_NAME", "demo"),
                        ("ODOO_API_USER", "me@example.test"), ("ODOO_API_KEY", KEY)):
        monkeypatch.setenv(name, value)
    return fake


# ---- mapping ----------------------------------------------------------------------------

def test_open_invoices_are_mapped_to_the_contract(odoo):
    got = {i.invoice_id: i for i in reader.open_invoices()}
    assert set(got) == {"INV-11", "12", "INV-13"}                     # paid, no-due and no-customer ones are left out
    a = got["INV-11"]
    assert (a.customer_id, a.display_name, a.contact_email) == ("C100", "Khach A", "a@example.test")
    assert (a.invoice_amount, a.remaining_amount, a.due_date) == (250, 250, date(2026, 10, 20))
    assert a.dispute_status == "none" and a.currency == "VND"


def test_empty_odoo_fields_fall_back_like_the_sql_reader(odoo):
    b = next(i for i in reader.open_invoices() if i.invoice_id == "12")
    assert b.customer_id == "2" and b.contact_email is None           # no partner ref -> partner id, no e-mail
    assert b.due_date == date(2026, 10, 5)                            # no due date -> invoice date


def test_dispute_marker_in_the_note_is_detected(odoo):
    got = {i.invoice_id: i for i in reader.open_invoices()}
    assert got["INV-13"].dispute_status == "disputed" and got["INV-11"].dispute_status == "none"


def test_all_invoices_include_the_paid_ones(odoo):
    ids = {i.invoice_id for i in reader.all_invoices()}
    assert "INV-10" in ids and {"INV-11", "12", "INV-13"} <= ids


def test_payment_history_is_mapped_to_the_contract(odoo):
    got = {p.payment_id: p for p in reader.payment_history()}
    assert set(got) == {"900", "901"}                                 # the one without a date is left out
    assert (got["900"].invoice_id, got["900"].customer_id, got["900"].amount) == ("INV-10", "C100", 100)
    assert got["900"].payment_date == date(2026, 10, 3)
    assert (got["901"].invoice_id, got["901"].customer_id) == ("12", "2")


def test_results_page_through_large_tables_without_losing_or_repeating_rows(odoo, monkeypatch):
    monkeypatch.setattr(reader, "PAGE", 2)
    ids = [i.invoice_id for i in reader.all_invoices()]
    assert len(ids) == len(set(ids)) == 4                             # 6 moves, 2 skipped, none lost or doubled
    assert sum(1 for c in odoo.calls if c[0] == "account.move" and c[1] == "search_read") >= 3


def test_open_invoices_ask_odoo_for_posted_customer_invoices_with_a_balance(odoo):
    reader.open_invoices()
    domain = next(c[2]["domain"] for c in odoo.calls if c[0] == "account.move")
    assert ["move_type", "=", "out_invoice"] in domain and ["state", "=", "posted"] in domain
    assert ["amount_residual", ">", 0] in domain


# ---- read only --------------------------------------------------------------------------

def test_only_read_methods_are_ever_sent(odoo):
    reader.open_invoices(); reader.all_invoices(); reader.payment_history()
    assert odoo.calls and {c[1] for c in odoo.calls} <= reader.READ_METHODS


@pytest.mark.parametrize("method", ["write", "create", "unlink", "action_post", "execute"])
def test_write_methods_are_refused_before_any_request(odoo, method):
    client = reader._Client()
    with pytest.raises(ValueError):
        client.call("account.move", method, ids=[1])
    assert odoo.calls == []


# ---- transports -------------------------------------------------------------------------

def test_json2_sends_the_key_in_a_header_and_never_in_the_url(odoo):
    if odoo.transport != "json2":
        pytest.skip("json2 only")
    reader.open_invoices()
    assert all(KEY not in u for u in odoo.urls)
    assert odoo.headers[0]["Authorization"] == f"bearer {KEY}" and odoo.headers[0]["X-Odoo-Database"] == "demo"
    assert odoo.urls[0] == "https://demo.odoo.com/json/2/account.move/search_read"


def test_json2_needs_no_login_name(odoo, monkeypatch):
    if odoo.transport != "json2":
        pytest.skip("json2 only")
    monkeypatch.delenv("ODOO_API_USER")
    assert reader.open_invoices()


def test_xmlrpc_needs_the_login_name(odoo, monkeypatch):
    if odoo.transport != "xmlrpc":
        pytest.skip("xmlrpc only")
    monkeypatch.delenv("ODOO_API_USER")
    with pytest.raises(odoo_reader.OdooUnavailable, match="ODOO_API_USER"):
        reader.open_invoices()


def test_an_unknown_transport_is_rejected(odoo, monkeypatch):
    monkeypatch.setenv("ODOO_API_TRANSPORT", "soap")
    with pytest.raises(odoo_reader.OdooUnavailable, match="ODOO_API_TRANSPORT"):
        reader.open_invoices()


@pytest.mark.parametrize("pasted,expected", [
    ("https://demo.odoo.com", "https://demo.odoo.com"),
    ("https://demo.odoo.com/", "https://demo.odoo.com"),
    ("https://demo.odoo.com/odoo", "https://demo.odoo.com"),          # address copied from the browser
    ("  https://demo.odoo.com/odoo/action-123?x=1  ", "https://demo.odoo.com"),
    ("http://localhost:8069/web", "http://localhost:8069"),
    ("demo.odoo.com", ""),                                           # no scheme: treated as not configured
    ("", ""),
])
def test_the_url_is_reduced_to_scheme_and_host(pasted, expected):
    assert reader._origin(pasted) == expected


def test_a_pasted_browser_address_reaches_the_api_root(odoo, monkeypatch):
    monkeypatch.setenv("ODOO_URL", "https://demo.odoo.com/odoo")
    reader.open_invoices()
    assert odoo.urls and all(u.startswith("https://demo.odoo.com/") and "/odoo/" not in u for u in odoo.urls)


# ---- errors and secrets -----------------------------------------------------------------

def test_missing_settings_are_reported(monkeypatch):
    monkeypatch.setenv("ODOO_URL", "")
    with pytest.raises(odoo_reader.OdooUnavailable, match="not configured"):
        reader.open_invoices()


def test_wrong_login_is_reported_without_the_key(odoo):
    odoo.auth_ok = False
    with pytest.raises(odoo_reader.OdooUnavailable) as e:
        reader.open_invoices()
    assert KEY not in str(e.value) and "login failed" in str(e.value)


def test_missing_access_rights_are_not_reported_as_a_wrong_key(odoo):
    odoo.denied = True
    with pytest.raises(odoo_reader.OdooUnavailable) as e:
        reader.open_invoices()
    text = str(e.value)
    assert "login failed" not in text and "Invoicing" in text and KEY not in text


def test_a_server_fault_never_leaks_the_api_key(odoo):
    odoo.server_error = f"AccessDenied for key {KEY}\nTraceback " + "x" * 500
    with pytest.raises(odoo_reader.OdooUnavailable) as e:
        reader.open_invoices()
    assert KEY not in str(e.value) and len(str(e.value)) < 300


def test_an_unreachable_server_is_reported(odoo):
    odoo.down = True
    with pytest.raises(odoo_reader.OdooUnavailable, match="cannot reach"):
        reader.open_invoices()


# ---- choosing the reader ----------------------------------------------------------------

def test_odoo_mode_selects_the_reader(monkeypatch):
    monkeypatch.delenv("ODOO_MODE", raising=False)
    assert sources.odoo() is odoo_reader                              # default: SQL
    monkeypatch.setenv("ODOO_MODE", "api")
    assert sources.odoo() is reader
    monkeypatch.setenv("ODOO_MODE", "ftp")
    with pytest.raises(ValueError):
        sources.odoo()


def test_the_whole_api_runs_on_the_api_reader(odoo, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_SOURCE", "odoo")
    monkeypatch.setenv("ODOO_MODE", "api")
    monkeypatch.setenv("AS_OF_DATE", "2026-11-09")
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    client = TestClient(app)
    tok = client.post("/api/auth/login", json={"username": "accountant1", "password": "demo123"}).json()["access_token"]
    h = {"Authorization": "Bearer " + tok}
    inv = client.get("/api/invoices/open", headers=h).json()
    assert inv["source"] == "odoo" and {i["invoice_id"] for i in inv["items"]} == {"INV-11", "12", "INV-13"}
    assert len(client.get("/api/payments/history", headers=h).json()["items"]) == 2
    preds = client.get("/api/predictions", headers=h).json()["items"]
    assert {p["invoice_id"] for p in preds} == {"INV-11", "12", "INV-13"}
    assert {c[1] for c in odoo.calls} <= reader.READ_METHODS          # still nothing but reads
