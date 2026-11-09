import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.contracts import Prediction
from app.main import app

FIX = Path(__file__).resolve().parents[2] / "fixtures"
client = TestClient(app)


@pytest.fixture(autouse=True)
def _fixture_mode(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "fixture")
    monkeypatch.setenv("AS_OF_DATE", "2026-11-09")


def _token(username):
    r = client.post("/api/auth/login", json={"username": username, "password": "demo123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_requires_a_token():
    assert client.get("/api/predictions").status_code == 401


@pytest.mark.parametrize("user", ["viewer1", "admin1"])
def test_other_roles_are_forbidden(user):
    assert client.get("/api/predictions", headers=_token(user)).status_code == 403


@pytest.mark.parametrize("user", ["accountant1", "manager1"])
def test_accountant_and_manager_get_a_prediction_for_every_open_invoice(user):
    r = client.get("/api/predictions", headers=_token(user))
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fixture" and body["as_of_date"] == "2026-11-09"
    invoices = json.loads((FIX / "invoices.json").read_text(encoding="utf-8"))
    open_ids = [i["invoice_id"] for i in invoices if i["remaining_amount"] > 0]
    assert [p["invoice_id"] for p in body["items"]] == open_ids
    for item in body["items"]:
        p = Prediction(**item)                     # response matches the shared contract
        assert p.predicted_date_p25 <= p.predicted_date_p50 <= p.predicted_date_p75


def test_response_marks_low_history_and_overdue_adjustments():
    items = client.get("/api/predictions", headers=_token("accountant1")).json()["items"]
    by_method = {i["method"] for i in items}
    assert by_method <= {"customer_median", "global_median", "no_history"}
    assert all(i["low_history"] for i in items if i["method"] != "customer_median")
