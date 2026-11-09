import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.forecast import Obligation
from app.main import app
from app.obligations import ObligationRecord
from app.routes_f4 import obligation_repo

FIX = Path(__file__).resolve().parents[2] / "fixtures"


class MemoryObligations:
    """Stand-in for the PostgreSQL repository, so the API logic is tested without a database."""

    def __init__(self):
        self.rows: list[ObligationRecord] = []

    def add(self, ob: Obligation, created_by: str) -> ObligationRecord:
        rec = ObligationRecord(id=len(self.rows) + 1, description=ob.description.strip(), amount=ob.amount,
                               due_date=ob.due_date, created_by=created_by,
                               created_at=datetime(2026, 11, 9, tzinfo=timezone.utc))
        self.rows.append(rec)
        return rec

    def list_all(self):
        return sorted(self.rows, key=lambda r: (r.due_date, r.id))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_SOURCE", "fixture")
    monkeypatch.setenv("AS_OF_DATE", "2026-11-09")
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    memory = MemoryObligations()
    app.dependency_overrides[obligation_repo] = lambda: memory
    yield memory
    app.dependency_overrides.clear()


client = TestClient(app)


def auth(username="accountant1"):
    r = client.post("/api/auth/login", json={"username": username, "password": "demo123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def good(**over):
    return {"description": "Tien thue van phong", "amount": 70_000_000, "due_date": "2026-11-12", **over}


# ---- access -----------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [("get", "/api/f4/forecast"), ("get", "/api/f4/obligations"),
                                         ("post", "/api/f4/obligations")])
def test_requires_a_token(repo, method, path):
    kwargs = {"json": good()} if method == "post" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("user", ["viewer1", "admin1"])
def test_viewer_and_admin_cannot_use_f4(repo, user):
    assert client.get("/api/f4/forecast", headers=auth(user)).status_code == 403
    assert client.post("/api/f4/obligations", json=good(), headers=auth(user)).status_code == 403
    assert repo.rows == []


# ---- saving an expense ------------------------------------------------------------------

@pytest.mark.parametrize("user", ["accountant1", "manager1"])
def test_accountant_and_manager_can_save_an_expense(repo, user):
    r = client.post("/api/f4/obligations", json=good(), headers=auth(user))
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1 and body["amount"] == 70_000_000 and body["created_by"] == user
    assert [x.amount for x in repo.rows] == [70_000_000]


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -5}, {"amount": "abc"}, {"amount": 1.5},
    {"description": ""}, {"description": "x" * 201},
    {"due_date": "not-a-date"}, {"due_date": "2026-13-45"},
    {"currency": "USD"},
])
def test_invalid_expenses_are_rejected_and_not_saved(repo, bad):
    r = client.post("/api/f4/obligations", json=good(**bad), headers=auth())
    assert r.status_code == 422
    assert repo.rows == []


@pytest.mark.parametrize("missing", ["description", "amount", "due_date"])
def test_missing_fields_are_rejected(repo, missing):
    body = good()
    del body[missing]
    assert client.post("/api/f4/obligations", json=body, headers=auth()).status_code == 422
    assert repo.rows == []


def test_saving_an_expense_is_written_to_the_audit_log(repo):
    from app import audit
    client.post("/api/f4/obligations", json=good(), headers=auth())
    entry = next(e for e in audit.list_audit() if e["action"] == "obligation_created")
    assert entry["actor"] == "accountant1" and entry["target"] == "obligation:1"


def test_saved_expenses_are_listed_and_marked_manual(repo):
    client.post("/api/f4/obligations", json=good(description="Luong", due_date="2026-11-20"), headers=auth())
    client.post("/api/f4/obligations", json=good(), headers=auth())
    body = client.get("/api/f4/obligations", headers=auth()).json()
    assert body["source"] == "manual"
    assert [i["description"] for i in body["items"]] == ["Tien thue van phong", "Luong"]


# ---- forecast and alert -----------------------------------------------------------------

def test_forecast_has_twelve_weeks_three_scenarios_and_is_labelled(repo):
    body = client.get("/api/f4/forecast", headers=auth()).json()
    assert len(body["weeks"]) == 12
    assert body["weeks"][0]["week_start"] == "2026-11-09"
    assert body["as_of_date"] == "2026-11-09" and body["source"] == "fixture"
    assert body["obligations_source"] == "manual"
    assert {"receipt_p25", "receipt_p50", "receipt_p75", "obligations", "gap_p75"} <= body["weeks"][0].keys()
    assert body["alerts"] == []                                        # no expenses entered yet


def test_forecast_weeks_parameter_is_validated(repo):
    assert len(client.get("/api/f4/forecast?weeks=4", headers=auth()).json()["weeks"]) == 4
    for bad in ("0", "53", "x"):
        assert client.get(f"/api/f4/forecast?weeks={bad}", headers=auth()).status_code == 422


def test_forecast_money_adds_up_for_every_scenario(repo):
    """Receipts inside the weeks + money beyond them = total still owed on open invoices."""
    body = client.get("/api/f4/forecast", headers=auth()).json()
    invoices = json.loads((FIX / "invoices.json").read_text(encoding="utf-8"))
    total = sum(i["remaining_amount"] for i in invoices)
    for key in ("p25", "p50", "p75"):
        inside = sum(w[f"receipt_{key}"] for w in body["weeks"])
        assert inside + body["receipts_out_of_horizon"][key] == total


def test_a_big_expense_raises_an_alert_with_the_exact_gap(repo):
    before = client.get("/api/f4/forecast", headers=auth()).json()
    week = before["weeks"][0]
    spend = week["receipt_p75"] + 30_000_000                    # QA05 shape: expense exceeds P75 receipts by 30m
    client.post("/api/f4/obligations", json=good(amount=spend, due_date="2026-11-11"), headers=auth())
    after = client.get("/api/f4/forecast", headers=auth()).json()
    assert after["weeks"][0]["obligations"] == spend
    assert after["weeks"][0]["gap_p75"] == 30_000_000
    assert after["alerts"] == [{"week_start": "2026-11-09", "receipt_p75": week["receipt_p75"],
                                "obligations": spend, "gap_p75": 30_000_000}]


def test_an_expense_covered_by_receipts_raises_no_alert(repo):
    client.post("/api/f4/obligations", json=good(amount=1_000, due_date="2026-11-11"), headers=auth())
    assert client.get("/api/f4/forecast", headers=auth()).json()["alerts"] == []


def test_forecast_reflects_the_repo_so_a_reload_shows_saved_expenses(repo):
    client.post("/api/f4/obligations", json=good(), headers=auth())
    again = client.get("/api/f4/forecast", headers=auth()).json()
    assert sum(w["obligations"] for w in again["weeks"]) == 70_000_000


def test_database_down_gives_503_not_a_crash(repo):
    from app import db

    class Broken:
        def add(self, *a, **k): raise db.AppDbUnavailable("down")
        def list_all(self): raise db.AppDbUnavailable("down")

    app.dependency_overrides[obligation_repo] = lambda: Broken()
    assert client.post("/api/f4/obligations", json=good(), headers=auth()).status_code == 503
    assert client.get("/api/f4/forecast", headers=auth()).status_code == 503
