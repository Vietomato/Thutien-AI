"""Shared test setup.

API tests run against a REAL PostgreSQL database named thutien_test (never the live thutien_app).
They need APP_DB_PASSWORD set; without it (or without the database) they are skipped, not failed.
Odoo is replaced by an in-memory fake for permission and workflow tests, so the expected data is
known. One separate integration test reads the real Odoo database."""
import os
from datetime import date

import pytest

os.environ["APP_DB_NAME"] = "thutien_test"  # must be set before any app code connects

from fastapi.testclient import TestClient  # noqa: E402

from app import db, odoo_reader, users  # noqa: E402
from app.contracts import Invoice  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "Passw0rd!test"
AS_OF = date(2026, 11, 9)


@pytest.fixture
def clean_db():
    try:
        db.init_schema()
    except db.AppDbUnavailable as e:
        pytest.skip(f"test database not available: {e}")
    with db.connect() as conn:
        conn.execute("TRUNCATE audit_log, reminder_drafts, tasks, obligations, users RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def client(clean_db):
    return TestClient(app)


def _inv(invoice_id, customer_id, name, due, amount, remaining=None, dispute="none"):
    return Invoice(invoice_id=invoice_id, customer_id=customer_id, display_name=name, due_date=due,
                   invoice_amount=amount, remaining_amount=amount if remaining is None else remaining,
                   dispute_status=dispute, contact_email=f"{customer_id.lower()}@example.test")


@pytest.fixture
def fake_odoo(monkeypatch):
    """Known data: C001 has one overdue invoice and one not yet due; C002 has a disputed one."""
    state = {
        "invoices": [
            _inv("INV-A", "C001", "Khach A", date(2026, 10, 10), 120_000_000),   # overdue 30
            _inv("INV-B", "C002", "Khach B", date(2026, 10, 20), 70_000_000, dispute="disputed"),
            _inv("INV-C", "C001", "Khach A", date(2026, 11, 24), 40_000_000),     # not due
            _inv("INV-D", "C003", "Khach C", date(2026, 11, 2), 90_000_000, 60_000_000),  # overdue 7, partial
        ],
        "delays": [("C001", 1), ("C001", 3), ("C001", 5), ("C001", 9), ("C003", 2)],
        "bills": [(date(2026, 11, 12), 500_000_000)],
    }

    def open_invoices(customer_id=None):
        return [i for i in state["invoices"] if customer_id is None or i.customer_id == customer_id]

    monkeypatch.setattr(odoo_reader, "open_invoices", open_invoices)
    monkeypatch.setattr(odoo_reader, "open_invoice",
                        lambda iid: next((i for i in state["invoices"] if i.invoice_id == iid), None))
    monkeypatch.setattr(odoo_reader, "payment_history", lambda customer_id=None: [])
    monkeypatch.setattr(odoo_reader, "paid_delays", lambda as_of_date=None: state["delays"])
    monkeypatch.setattr(odoo_reader, "supplier_bills", lambda: state["bills"])
    monkeypatch.setattr(odoo_reader, "customers", lambda: [
        {"customer_id": "C001", "name": "Khach A"}, {"customer_id": "C002", "name": "Khach B"}])
    return state


@pytest.fixture
def make_user(clean_db):
    def make(username, role, **kw):
        return users.create_user(username, username.title(), PASSWORD, role, **kw)
    return make


@pytest.fixture
def auth(client):
    def login(username, password=PASSWORD) -> dict:
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return login


@pytest.fixture
def team(make_user):
    """chief1 supervises acc1; chief2 supervises acc2; plus a customer linked to C001 and an admin."""
    chief1 = make_user("chief1", "chief_accountant")
    chief2 = make_user("chief2", "chief_accountant")
    acc1 = make_user("acc1", "accountant", supervisor_id=chief1["id"])
    acc2 = make_user("acc2", "accountant", supervisor_id=chief2["id"])
    cust = make_user("cust1", "customer", customer_id="C001")
    admin = make_user("admin1", "admin")
    return {"chief1": chief1, "chief2": chief2, "acc1": acc1, "acc2": acc2, "cust": cust, "admin": admin}
