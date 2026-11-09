from fastapi.testclient import TestClient
from decimal import Decimal

from app.main import app

client = TestClient(app)


def _live_data():
    return {
        "as_of_date": "2026-11-09",
        "data_mode": "live",
        "invoices": [
            {
                "invoice_id": "INV-1",
                "customer_id": "C-1",
                "display_name": "Customer One",
                "due_date": "2026-11-05",
                "invoice_amount": "100000000",
                "remaining_amount": "80000000",
                "currency": "VND",
                "dispute_status": None,
                "contact_email": "ar@example.test",
            }
        ],
        "completed_invoice_history": [
            {
                "invoice_id": "HIST-1",
                "customer_id": "C-1",
                "due_date": "2026-10-01",
                "completed_date": "2026-10-03",
            },
            {
                "invoice_id": "HIST-2",
                "customer_id": "C-1",
                "due_date": "2026-10-01",
                "completed_date": "2026-10-01",
            },
        ],
        "predictions": {"INV-1": {"method": "customer_median"}},
        "active_draft_invoice_ids": [],
    }


def test_priority_api_fails_closed_until_auth_and_live_provider_exist():
    response = client.get("/api/f3/priority")
    assert response.status_code == 503
    assert "authorization" in response.json()["detail"]


def test_priority_api_checks_access_and_returns_provider_data(monkeypatch):
    monkeypatch.setattr(app.state, "f3_authorize_detail", lambda request, scope: True, raising=False)
    monkeypatch.setattr(app.state, "f3_priority_provider", _live_data, raising=False)

    response = client.get("/api/f3/priority")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "live"
    assert Decimal(payload["items"][0]["priority_score"]) == Decimal("160000000")
    assert payload["items"][0]["prediction"]["method"] == "customer_median"


def test_priority_api_denies_unauthorized_roles(monkeypatch):
    monkeypatch.setattr(app.state, "f3_authorize_detail", lambda request, scope: False, raising=False)
    monkeypatch.setattr(app.state, "f3_priority_provider", _live_data, raising=False)

    response = client.get("/api/f3/priority")

    assert response.status_code == 403
