import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DATA_SOURCE", "fixture")


def _headers(username: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": "demo123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_is_public():
    assert client.get("/health").status_code == 200


def test_no_token_is_401():
    assert client.get("/api/invoices/open").status_code == 401


def test_garbage_token_is_401():
    r = client.get("/api/invoices/open", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 401


def test_wrong_password_is_401():
    r = client.post("/api/auth/login", json={"username": "accountant1", "password": "nope"})
    assert r.status_code == 401


def test_accountant_can_read_invoices():
    r = client.get("/api/invoices/open", headers=_headers("accountant1"))
    assert r.status_code == 200
    assert r.json()["source"] == "fixture"


def test_viewer_and_admin_are_403():
    for user in ("viewer1", "admin1"):
        r = client.get("/api/invoices/open", headers=_headers(user))
        assert r.status_code == 403
        r = client.get("/api/payments/history", headers=_headers(user))
        assert r.status_code == 403