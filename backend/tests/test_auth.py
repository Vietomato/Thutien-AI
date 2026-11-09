from app import audit, users
from conftest import PASSWORD


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["app_db"] == "ok"


def test_no_token_is_401(client):
    assert client.get("/api/invoices/open").status_code == 401


def test_garbage_token_is_401(client):
    assert client.get("/api/invoices/open", headers={"Authorization": "Bearer abc"}).status_code == 401


def test_login_returns_role_and_permissions(client, team):
    r = client.post("/api/auth/login", json={"username": "chief1", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "chief_accountant" and "draft:decide" in body["permissions"]
    assert "password" not in str(body).lower().replace("permissions", "")


def test_username_is_case_insensitive(client, team):
    assert client.post("/api/auth/login", json={"username": "ChIeF1", "password": PASSWORD}).status_code == 200


def test_wrong_password_and_unknown_user_look_the_same(client, team):
    a = client.post("/api/auth/login", json={"username": "chief1", "password": "nope"})
    b = client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert {r["action"] for r in audit.list_audit()} == {"login_failed"}


def test_account_locks_after_repeated_failures(client, team):
    for _ in range(users.MAX_FAILED_LOGINS):
        assert client.post("/api/auth/login", json={"username": "acc1", "password": "bad"}).status_code == 401
    # Even the right password is refused while locked.
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 429


def test_successful_login_resets_the_counter(client, team):
    for _ in range(users.MAX_FAILED_LOGINS - 1):
        client.post("/api/auth/login", json={"username": "acc1", "password": "bad"})
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "acc1", "password": "bad"}).status_code == 401


def test_deactivated_user_cannot_log_in_and_old_token_dies(client, team, auth):
    headers = auth("acc1")
    users.update_user(team["acc1"]["id"], {"is_active": False})
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 401


def test_role_change_applies_to_existing_token(client, team, auth, fake_odoo):
    headers = auth("acc1")
    assert client.get("/api/forecast", headers=headers).status_code == 200
    users.update_user(team["acc1"]["id"], {"role": "customer"})
    assert client.get("/api/forecast", headers=headers).status_code == 403


def test_register_creates_unlinked_customer(client, fake_odoo):
    r = client.post("/api/auth/register", json={"username": "New.User", "full_name": "New User", "password": "longenough1"})
    assert r.status_code == 201 and r.json()["role"] == "customer" and r.json()["customer_id"] is None
    token = client.post("/api/auth/login", json={"username": "new.user", "password": "longenough1"}).json()["access_token"]
    items = client.get("/api/invoices/open", headers={"Authorization": f"Bearer {token}"}).json()["items"]
    assert items == []  # linked to no customer, sees nothing


def test_register_rejects_bad_input(client):
    ok = {"username": "valid.name", "full_name": "A", "password": "longenough1"}
    assert client.post("/api/auth/register", json={**ok, "username": "x"}).status_code == 422
    assert client.post("/api/auth/register", json={**ok, "username": "has space"}).status_code == 422
    assert client.post("/api/auth/register", json={**ok, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={**ok, "role": "admin"}).status_code == 201  # extra field ignored
    assert client.post("/api/auth/register", json=ok).status_code == 409


def test_registration_cannot_choose_a_role(client):
    client.post("/api/auth/register", json={"username": "sneaky", "full_name": "S", "password": "longenough1", "role": "admin"})
    assert users.get_by_username("sneaky")["role"] == "customer"


def test_change_password(client, team, auth):
    headers = auth("acc1")
    assert client.post("/api/auth/change-password", headers=headers,
                       json={"old_password": "wrong", "new_password": "brandnewpass1"}).status_code == 400
    assert client.post("/api/auth/change-password", headers=headers,
                       json={"old_password": PASSWORD, "new_password": "short"}).status_code == 422
    assert client.post("/api/auth/change-password", headers=headers,
                       json={"old_password": PASSWORD, "new_password": "brandnewpass1"}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "acc1", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "acc1", "password": "brandnewpass1"}).status_code == 200


def test_logout_is_audited(client, team, auth):
    client.post("/api/auth/logout", headers=auth("acc1"))
    assert audit.list_audit(action="logout")[0]["actor"] == "acc1"


def test_passwords_never_appear_in_audit(client, team, auth):
    client.post("/api/auth/login", json={"username": "acc1", "password": "secret-attempt"})
    assert "secret-attempt" not in str(audit.list_audit())
