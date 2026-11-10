def assign(client, headers, assignee_id, invoice_id="INV-A", **kw):
    return client.post("/api/tasks", json={"invoice_id": invoice_id, "assignee_id": assignee_id, **kw}, headers=headers)


def test_chief_assigns_to_own_team_member(client, team, auth, fake_odoo):
    r = assign(client, auth("chief1"), team["acc1"]["id"], note="Gọi điện trước")
    assert r.status_code == 201
    t = r.json()
    assert t["assignee_username"] == "acc1" and t["created_by_username"] == "chief1" and t["status"] == "open"
    assert "INV-A" in t["title"] and t["note"] == "Gọi điện trước"


def test_chief_cannot_assign_outside_the_team_or_unknown_invoice(client, team, auth, fake_odoo):
    assert assign(client, auth("chief1"), team["acc2"]["id"]).status_code == 403      # acc2 belongs to chief2
    assert assign(client, auth("chief1"), team["cust"]["id"]).status_code == 403
    assert assign(client, auth("chief1"), team["acc1"]["id"], invoice_id="NOPE").status_code == 404
    assert assign(client, auth("chief1"), team["chief1"]["id"]).status_code == 201     # to themselves is fine


def test_accountant_cannot_assign(client, team, auth, fake_odoo):
    assert assign(client, auth("acc1"), team["acc1"]["id"]).status_code == 403


def test_accountant_sees_only_own_tasks_and_cannot_use_team_scope(client, team, auth, fake_odoo):
    assign(client, auth("chief1"), team["acc1"]["id"])
    assign(client, auth("chief2"), team["acc2"]["id"], invoice_id="INV-D")
    mine = client.get("/api/tasks", headers=auth("acc1")).json()["items"]
    assert [t["invoice_id"] for t in mine] == ["INV-A"]
    assert client.get("/api/tasks?scope=team", headers=auth("acc1")).status_code == 403


def test_chief_sees_own_teams_tasks_only(client, team, auth, fake_odoo):
    assign(client, auth("chief1"), team["acc1"]["id"])
    assign(client, auth("chief2"), team["acc2"]["id"], invoice_id="INV-D")
    seen = client.get("/api/tasks?scope=team", headers=auth("chief1")).json()["items"]
    assert [t["assignee_username"] for t in seen] == ["acc1"]
    assert client.get("/api/tasks?scope=team", headers=auth("chief2")).json()["items"][0]["assignee_username"] == "acc2"


def test_chief_team_scope_includes_tasks_assigned_to_self(client, team, auth, fake_odoo):
    assign(client, auth("chief1"), team["chief1"]["id"])
    seen = client.get("/api/tasks?scope=team", headers=auth("chief1")).json()["items"]
    assert [t["assignee_username"] for t in seen] == ["chief1"]


def test_team_list_contains_only_own_team_and_self(client, team, auth, fake_odoo):
    names = [m["username"] for m in client.get("/api/team", headers=auth("chief1")).json()["items"]]
    assert names == ["chief1", "acc1"]


def test_assignee_completes_task_others_cannot(client, team, auth, fake_odoo):
    t = assign(client, auth("chief1"), team["acc1"]["id"]).json()
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=auth("acc2")).status_code == 404
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=auth("chief2")).status_code == 404
    done = client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=auth("acc1")).json()
    assert done["status"] == "done" and done["done_at"]
    reopened = client.patch(f"/api/tasks/{t['id']}", json={"status": "open"}, headers=auth("chief1")).json()
    assert reopened["status"] == "open" and reopened["done_at"] is None


def test_invalid_status_is_rejected(client, team, auth, fake_odoo):
    t = assign(client, auth("chief1"), team["acc1"]["id"]).json()
    assert client.patch(f"/api/tasks/{t['id']}", json={"status": "weird"}, headers=auth("acc1")).status_code == 422
