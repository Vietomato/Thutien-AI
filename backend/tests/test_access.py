"""Who can call what. Every endpoint is checked against every role."""
import pytest

from app import audit

# endpoint -> roles that must get 200. Everyone else must get 403.
READ_ENDPOINTS = {
    "/api/invoices/open": {"accountant", "chief_accountant", "customer"},
    "/api/payments/history": {"accountant", "chief_accountant", "customer"},
    "/api/summary": {"accountant", "chief_accountant", "customer"},
    "/api/predictions": {"accountant", "chief_accountant"},
    "/api/forecast": {"accountant", "chief_accountant"},
    "/api/reminders/drafts": {"accountant", "chief_accountant"},
    "/api/reminders/candidates": {"accountant", "chief_accountant"},
    "/api/tasks": {"accountant", "chief_accountant"},
    "/api/team": {"chief_accountant"},
    "/api/admin/users": {"admin"},
    "/api/admin/audit": {"admin"},
    "/api/admin/customers": {"admin"},
}
USER_FOR_ROLE = {"accountant": "acc1", "chief_accountant": "chief1", "customer": "cust1", "admin": "admin1"}


@pytest.mark.parametrize("path", sorted(READ_ENDPOINTS))
def test_endpoint_matrix(client, team, auth, fake_odoo, path):
    for role, username in USER_FOR_ROLE.items():
        r = client.get(path, headers=auth(username))
        expected = 200 if role in READ_ENDPOINTS[path] else 403
        assert r.status_code == expected, f"{role} on {path}: got {r.status_code}"


@pytest.mark.parametrize("path", sorted(READ_ENDPOINTS))
def test_every_endpoint_requires_login(client, team, fake_odoo, path):
    assert client.get(path).status_code == 401


def test_customer_sees_only_own_invoices(client, team, auth, fake_odoo):
    items = client.get("/api/invoices/open", headers=auth("cust1")).json()["items"]
    assert {i["customer_id"] for i in items} == {"C001"} and len(items) == 2
    s = client.get("/api/summary", headers=auth("cust1")).json()
    assert s["scope"] == "own" and s["total_remaining"] == 160_000_000  # INV-A + INV-C, not the others


def test_staff_see_everything(client, team, auth, fake_odoo):
    assert len(client.get("/api/invoices/open", headers=auth("acc1")).json()["items"]) == 4
    assert client.get("/api/summary", headers=auth("chief1")).json()["total_remaining"] == 290_000_000


def test_customer_cannot_see_other_customers_through_any_field(client, team, auth, fake_odoo):
    text = client.get("/api/invoices/open", headers=auth("cust1")).text
    assert "C002" not in text and "C003" not in text and "Khach B" not in text


def test_forbidden_attempts_are_audited(client, team, auth, fake_odoo):
    client.get("/api/forecast", headers=auth("cust1"))
    row = audit.list_audit(action="forbidden")[0]
    assert row["actor"] == "cust1" and row["detail"]["role"] == "customer"


def test_forecast_and_predictions_come_from_the_fake_data(client, team, auth, fake_odoo):
    f = client.get("/api/forecast", headers=auth("acc1")).json()
    assert len(f["weeks"]) == 12 and f["source"] == "odoo"
    assert f["weeks"][0]["obligations"] == 500_000_000 and f["risky_weeks"] >= 1
    p = client.get("/api/predictions", headers=auth("acc1")).json()["items"]
    assert "INV-B" not in {i["invoice_id"] for i in p}  # disputed: no prediction


def test_customer_without_link_sees_nothing(client, make_user, auth, fake_odoo):
    make_user("lonely", "customer")
    r = client.get("/api/invoices/open", headers=auth("lonely"))
    assert r.status_code == 200 and r.json()["items"] == []
    assert client.get("/api/summary", headers=auth("lonely")).json()["total_remaining"] == 0


def test_odoo_down_is_502_without_leaking_details(client, team, auth, monkeypatch):
    from app import odoo_reader

    def boom(*a, **k):
        raise odoo_reader.OdooUnavailable("cannot connect to Odoo DB: host=10.0.0.5 password=hunter2")
    monkeypatch.setattr(odoo_reader, "open_invoices", boom)
    r = client.get("/api/invoices/open", headers=auth("acc1"))
    assert r.status_code == 502 and "hunter2" not in r.text and "10.0.0.5" not in r.text
