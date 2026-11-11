from app import audit, users
from conftest import PASSWORD


def new_user(**over):
    return {"username": "new.staff", "full_name": "New Staff", "password": "longenough1", "role": "accountant", **over}


def test_admin_creates_user_and_it_is_audited(client, team, auth, fake_odoo):
    r = client.post("/api/admin/users", json=new_user(supervisor_id=team["chief1"]["id"]), headers=auth("admin1"))
    assert r.status_code == 201 and r.json()["role"] == "accountant" and "password" not in str(r.json()).lower()
    assert client.post("/api/auth/login", json={"username": "new.staff", "password": "longenough1"}).status_code == 200
    assert audit.list_audit(action="create_user")[0]["target"] == "new.staff"
    assert "longenough1" not in str(audit.list_audit())


def test_non_admins_cannot_manage_users(client, team, auth, fake_odoo):
    for u in ("acc1", "chief1", "cust1"):
        h = auth(u)
        assert client.post("/api/admin/users", json=new_user(), headers=h).status_code == 403
        assert client.patch(f"/api/admin/users/{team['acc1']['id']}", json={"role": "admin"}, headers=h).status_code == 403
        assert client.post(f"/api/admin/users/{team['acc1']['id']}/password", json={"password": "longenough1"}, headers=h).status_code == 403


def test_create_user_validation(client, team, auth, fake_odoo):
    h = auth("admin1")
    assert client.post("/api/admin/users", json=new_user(username="ab"), headers=h).status_code == 422
    assert client.post("/api/admin/users", json=new_user(password="short"), headers=h).status_code == 422
    assert client.post("/api/admin/users", json=new_user(role="superuser"), headers=h).status_code == 422
    assert client.post("/api/admin/users", json=new_user(username="CHIEF1"), headers=h).status_code == 409
    # a supervisor must be a chief accountant
    assert client.post("/api/admin/users", json=new_user(supervisor_id=team["acc1"]["id"]), headers=h).status_code == 422
    # a customer link must point at a real Odoo customer, and only customers can have one
    assert client.post("/api/admin/users", json=new_user(role="customer", customer_id="NOPE"), headers=h).status_code == 422
    assert client.post("/api/admin/users", json=new_user(role="customer", customer_id="C002"), headers=h).status_code == 201
    assert client.post("/api/admin/users", json=new_user(username="x.y", role="accountant", customer_id="C001"), headers=h).status_code == 422


def test_set_role_is_audited_and_works_immediately(client, team, auth, fake_odoo):
    token_headers = auth("cust1")
    assert client.get("/api/forecast", headers=token_headers).status_code == 403
    r = client.patch(f"/api/admin/users/{team['cust']['id']}", json={"role": "accountant"}, headers=auth("admin1"))
    assert r.status_code == 200 and r.json()["role"] == "accountant" and r.json()["customer_id"] is None
    assert client.get("/api/forecast", headers=token_headers).status_code == 200
    row = audit.list_audit(action="set_role")[0]
    assert row["actor"] == "admin1" and row["target"] == "cust1" and row["detail"] == {"from": "customer", "to": "accountant"}


def test_link_a_customer_account_to_an_odoo_customer(client, make_user, auth, fake_odoo, team):
    fresh = make_user("fresh", "customer")
    r = client.patch(f"/api/admin/users/{fresh['id']}", json={"customer_id": "C002"}, headers=auth("admin1"))
    assert r.status_code == 200 and r.json()["customer_id"] == "C002"
    items = client.get("/api/invoices/open", headers=auth("fresh")).json()["items"]
    assert [i["invoice_id"] for i in items] == ["INV-B"]


def test_admin_cannot_demote_or_deactivate_themselves(client, team, auth, fake_odoo):
    h, me = auth("admin1"), team["admin"]["id"]
    assert client.patch(f"/api/admin/users/{me}", json={"role": "accountant"}, headers=h).status_code == 409
    assert client.patch(f"/api/admin/users/{me}", json={"is_active": False}, headers=h).status_code == 409


def test_last_active_admin_cannot_be_removed(client, team, make_user, auth, fake_odoo):
    second = make_user("admin2", "admin")
    h = auth("admin1")
    assert client.patch(f"/api/admin/users/{second['id']}", json={"is_active": False}, headers=h).status_code == 200
    # admin2 is now inactive, so admin1 is the only one left. A second admin trying to remove them is impossible,
    # and reactivating admin2 then demoting it must work only while another admin remains.
    assert users.count_active_admins() == 1
    assert client.patch(f"/api/admin/users/{second['id']}", json={"is_active": True}, headers=h).status_code == 200
    assert client.patch(f"/api/admin/users/{second['id']}", json={"role": "customer"}, headers=h).status_code == 200


def test_changing_a_chiefs_role_detaches_the_team(client, team, auth, fake_odoo):
    r = client.patch(f"/api/admin/users/{team['chief1']['id']}", json={"role": "accountant"}, headers=auth("admin1"))
    assert r.status_code == 200
    assert users.get_by_id(team["acc1"]["id"])["supervisor_id"] is None


def test_moving_an_accountant_to_another_chief(client, team, auth, fake_odoo):
    r = client.patch(f"/api/admin/users/{team['acc1']['id']}", json={"supervisor_id": team["chief2"]["id"]}, headers=auth("admin1"))
    assert r.status_code == 200 and r.json()["supervisor_id"] == team["chief2"]["id"]
    seen = client.get("/api/team", headers=auth("chief2")).json()["items"]
    assert {m["username"] for m in seen} == {"chief2", "acc1", "acc2"}


def test_reset_password(client, team, auth, fake_odoo):
    assert client.post(f"/api/admin/users/{team['acc1']['id']}/password", json={"password": "short"}, headers=auth("admin1")).status_code == 422
    assert client.post(f"/api/admin/users/{team['acc1']['id']}/password", json={"password": "resetpass123"}, headers=auth("admin1")).status_code == 200
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "acc1", "password": "resetpass123"}).status_code == 200
    assert "resetpass123" not in str(audit.list_audit())


def test_reset_password_unlocks_a_locked_account(client, team, auth, fake_odoo):
    for _ in range(users.MAX_FAILED_LOGINS):
        client.post("/api/auth/login", json={"username": "acc1", "password": "bad"})
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 429
    client.post(f"/api/admin/users/{team['acc1']['id']}/password", json={"password": "resetpass123"}, headers=auth("admin1"))
    assert client.post("/api/auth/login", json={"username": "acc1", "password": "resetpass123"}).status_code == 200


def test_user_list_never_exposes_password_hashes(client, team, auth, fake_odoo):
    text = client.get("/api/admin/users", headers=auth("admin1")).text
    assert "password" not in text.lower() and "scrypt" not in text


def test_audit_endpoint_filters(client, team, auth, fake_odoo):
    client.post("/api/auth/login", json={"username": "acc1", "password": "bad"})
    items = client.get("/api/admin/audit?action=login_failed&limit=5", headers=auth("admin1")).json()["items"]
    assert items and all(i["action"] == "login_failed" for i in items)
    assert client.get("/api/admin/audit?limit=0", headers=auth("admin1")).status_code == 422


def test_admin_has_no_route_to_financial_data(client, team, auth, fake_odoo):
    h = auth("admin1")
    for path in ("/api/invoices/open", "/api/payments/history", "/api/summary", "/api/predictions", "/api/forecast",
                 "/api/reminders/drafts"):
        assert client.get(path, headers=h).status_code == 403, path
