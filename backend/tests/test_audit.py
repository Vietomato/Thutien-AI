from app import audit


def test_append_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "t.db"))
    audit_id = audit.append_audit("accountant1", "approve_draft", "INV-023", {"note": "ok"})
    rows = audit.list_audit()
    assert rows[0]["id"] == audit_id
    assert rows[0]["actor"] == "accountant1"
    assert rows[0]["target"] == "INV-023"


def test_secrets_are_masked(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "t.db"))
    audit.append_audit("admin", "login", "auth", {"password": "abc123", "ip": "1.2.3.4"})
    detail = audit.list_audit()[0]["detail"]
    assert detail["password"] == "***"
    assert detail["ip"] == "1.2.3.4"