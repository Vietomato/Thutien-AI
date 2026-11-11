from datetime import date

from app import audit
from app.contracts import Invoice


def create(client, headers, invoice_id="INV-A"):
    return client.post("/api/reminders/drafts", json={"invoice_id": invoice_id}, headers=headers)


def test_accountant_creates_a_draft_from_real_invoice_fields(client, team, auth, fake_odoo):
    r = create(client, auth("acc1"))
    assert r.status_code == 201
    d = r.json()
    assert d["status"] == "pending" and d["amount"] == 120_000_000 and d["overdue_days"] == 30
    assert d["generation_source"] == "template_fallback"
    assert "120.000.000" in d["body"] and "10/10/2026" in d["body"] and d["created_by_username"] == "acc1"
    assert d["checks_ok"] and all(c["ok"] for c in d["checks"])
    assert audit.list_audit(action="create_draft")[0]["target"] == "INV-A"


def test_cannot_draft_disputed_not_overdue_or_unknown_invoices(client, team, auth, fake_odoo):
    h = auth("acc1")
    assert create(client, h, "INV-B").status_code == 409   # disputed
    assert create(client, h, "INV-C").status_code == 409   # not overdue yet
    assert create(client, h, "NOPE").status_code == 404


def test_only_one_pending_draft_per_invoice(client, team, auth, fake_odoo):
    assert create(client, auth("acc1")).status_code == 201
    assert create(client, auth("acc2")).status_code == 409


def test_accountant_cannot_approve_or_reject(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    for action in ("approve", "reject"):
        assert client.post(f"/api/reminders/drafts/{d['id']}/{action}", headers=auth("acc1")).status_code == 403
    assert client.get(f"/api/reminders/drafts/{d['id']}", headers=auth("acc1")).json()["status"] == "pending"


def test_customer_and_admin_cannot_touch_drafts(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    for u in ("cust1", "admin1"):
        assert client.get(f"/api/reminders/drafts/{d['id']}", headers=auth(u)).status_code == 403
        assert create(client, auth(u), "INV-D").status_code == 403


def test_chief_approves_a_team_members_draft(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    r = client.post(f"/api/reminders/drafts/{d['id']}/approve", json={"note": "OK"}, headers=auth("chief1"))
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "approved" and out["decided_by_username"] == "chief1" and out["decision_note"] == "OK"
    row = audit.list_audit(action="approve_draft")[0]
    assert row["actor"] == "chief1" and row["target"] == "INV-A" and row["detail"]["drafted_by"] == "acc1"


def test_chief_cannot_decide_own_draft_or_edit_teammates_draft(client, team, auth, fake_odoo):
    own = create(client, auth("chief1"), "INV-A").json()
    for action in ("approve", "reject"):
        response = client.post(f"/api/reminders/drafts/{own['id']}/{action}", headers=auth("chief1"))
        assert response.status_code == 403
    teammate = create(client, auth("acc1"), "INV-D").json()
    assert client.patch(f"/api/reminders/drafts/{teammate['id']}",
                        json={"body": "changed"}, headers=auth("chief1")).status_code == 403
    assert client.get(f"/api/reminders/drafts/{own['id']}", headers=auth("chief1")).json()["status"] == "pending"


def test_approval_rechecks_odoo_version_and_contact(client, team, auth, fake_odoo):
    fake_odoo["invoices"][0] = fake_odoo["invoices"][0].model_copy(update={"source_version": "v1"})
    d = create(client, auth("acc1")).json()
    assert d["source_version"] == "v1"
    fake_odoo["invoices"][0] = fake_odoo["invoices"][0].model_copy(update={"source_version": "v2"})
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 409
    fake_odoo["invoices"][0] = fake_odoo["invoices"][0].model_copy(update={"source_version": "v1", "contact_email": "new@example.test"})
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 409
    assert client.get(f"/api/reminders/drafts/{d['id']}", headers=auth("chief1")).json()["checks_ok"] is False


def test_draft_history_is_scoped_and_records_edit_and_decision(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    client.patch(f"/api/reminders/drafts/{d['id']}", json={"body": "Reviewed"}, headers=auth("acc1"))
    client.post(f"/api/reminders/drafts/{d['id']}/reject", json={"note": "Check invoice"}, headers=auth("chief1"))
    path = f"/api/reminders/drafts/{d['id']}/history"
    for username in ("acc1", "chief1"):
        response = client.get(path, headers=auth(username))
        assert response.status_code == 200
        assert [x["action"] for x in response.json()["items"]] == ["create_draft", "edit_draft", "reject_draft"]
        assert response.json()["items"][-1]["detail"]["note"] == "Check invoice"
    assert client.get(path, headers=auth("chief2")).status_code == 404
    assert client.get(path, headers=auth("cust1")).status_code == 403


def test_decision_rolls_back_when_audit_write_fails(client, team, auth, fake_odoo, monkeypatch):
    from app import drafts
    d = create(client, auth("acc1")).json()

    def broken_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(drafts, "append_audit", broken_audit)
    try:
        client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected audit failure")
    assert client.get(f"/api/reminders/drafts/{d['id']}", headers=auth("chief1")).json()["status"] == "pending"


def test_chief_rejects(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    r = client.post(f"/api/reminders/drafts/{d['id']}/reject", headers=auth("chief1"))
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    # After a rejection a fresh draft can be written.
    assert create(client, auth("acc1")).status_code == 201


def test_a_decision_cannot_be_decided_twice(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 200
    assert client.post(f"/api/reminders/drafts/{d['id']}/reject", headers=auth("chief1")).status_code == 409
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 409


def test_chief_cannot_see_or_decide_another_chiefs_team(client, team, auth, fake_odoo):
    d = create(client, auth("acc2")).json()  # acc2 belongs to chief2
    assert client.get(f"/api/reminders/drafts/{d['id']}", headers=auth("chief1")).status_code == 404
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 404
    assert client.get("/api/reminders/drafts", headers=auth("chief1")).json()["items"] == []
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief2")).status_code == 200


def test_accountant_sees_only_own_drafts(client, team, auth, fake_odoo):
    create(client, auth("acc1"), "INV-A")
    create(client, auth("acc2"), "INV-D")
    mine = client.get("/api/reminders/drafts", headers=auth("acc1")).json()["items"]
    assert [x["invoice_id"] for x in mine] == ["INV-A"]
    team_view = client.get("/api/reminders/drafts", headers=auth("chief1")).json()["items"]
    assert [x["invoice_id"] for x in team_view] == ["INV-A"]  # chief1 only has acc1
    d2 = [x for x in client.get("/api/reminders/drafts", headers=auth("chief2")).json()["items"]]
    assert [x["invoice_id"] for x in d2] == ["INV-D"]
    other = client.get("/api/reminders/drafts/2", headers=auth("acc1"))
    assert other.status_code == 404


def test_approval_is_refused_when_odoo_data_changed(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    # Someone paid part of the invoice in Odoo after the draft was written.
    fake_odoo["invoices"][0] = Invoice(invoice_id="INV-A", customer_id="C001", display_name="Khach A",
                                       due_date=date(2026, 10, 10), invoice_amount=120_000_000,
                                       remaining_amount=70_000_000)
    got = client.get(f"/api/reminders/drafts/{d['id']}", headers=auth("chief1")).json()
    assert not got["checks_ok"] and any("không khớp" in c["label"] for c in got["checks"])
    r = client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1"))
    assert r.status_code == 409
    assert client.post(f"/api/reminders/drafts/{d['id']}/reject", headers=auth("chief1")).status_code == 200


def test_approval_is_refused_when_invoice_got_disputed(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    fake_odoo["invoices"][0] = Invoice(invoice_id="INV-A", customer_id="C001", display_name="Khach A",
                                       due_date=date(2026, 10, 10), invoice_amount=120_000_000,
                                       remaining_amount=120_000_000, dispute_status="disputed")
    assert client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1")).status_code == 409


def test_edit_only_while_pending_and_by_the_owner_side(client, team, auth, fake_odoo):
    d = create(client, auth("acc1")).json()
    assert client.patch(f"/api/reminders/drafts/{d['id']}", json={"body": "New text"}, headers=auth("acc1")).json()["body"] == "New text"
    assert client.patch(f"/api/reminders/drafts/{d['id']}", json={}, headers=auth("acc1")).status_code == 422
    assert client.patch(f"/api/reminders/drafts/{d['id']}", json={"body": "x"}, headers=auth("chief2")).status_code == 404
    client.post(f"/api/reminders/drafts/{d['id']}/approve", headers=auth("chief1"))
    assert client.patch(f"/api/reminders/drafts/{d['id']}", json={"body": "late edit"}, headers=auth("acc1")).status_code == 409


def test_candidates_lists_overdue_not_disputed_not_yet_drafted(client, team, auth, fake_odoo):
    c = client.get("/api/reminders/candidates", headers=auth("acc1")).json()
    assert [i["invoice_id"] for i in c["items"]] == ["INV-A", "INV-D"] and c["disputed"] == ["INV-B"]
    create(client, auth("acc1"), "INV-A")
    c = client.get("/api/reminders/candidates", headers=auth("acc1")).json()
    assert [i["invoice_id"] for i in c["items"]] == ["INV-D"]


def test_missing_email_is_not_a_reminder_candidate(client, team, auth, fake_odoo):
    fake_odoo["invoices"][0] = fake_odoo["invoices"][0].model_copy(update={"contact_email": None})
    candidates = client.get("/api/reminders/candidates", headers=auth("acc1")).json()["items"]
    assert "INV-A" not in [invoice["invoice_id"] for invoice in candidates]
    assert create(client, auth("acc1"), "INV-A").status_code == 409
