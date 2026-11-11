import pytest
from psycopg import errors as pg_errors

from app import audit, db


def test_append_and_list(clean_db):
    audit_id = audit.append_audit("accountant1", "approve_draft", "INV-023", {"note": "ok"})
    rows = audit.list_audit()
    assert rows[0]["id"] == audit_id
    assert rows[0]["actor"] == "accountant1"
    assert rows[0]["target"] == "INV-023"
    assert rows[0]["detail"] == {"note": "ok"}


def test_secrets_are_masked(clean_db):
    audit.append_audit("admin", "login", "auth", {"password": "abc123", "new_password": "x", "ip": "1.2.3.4"})
    detail = audit.list_audit()[0]["detail"]
    assert detail["password"] == "***" and detail["new_password"] == "***"
    assert detail["ip"] == "1.2.3.4"


def test_newest_first_and_filters(clean_db):
    audit.append_audit("a", "login", "auth")
    audit.append_audit("b", "forbidden", "api")
    audit.append_audit("a", "forbidden", "api")
    assert [r["actor"] for r in audit.list_audit()] == ["a", "b", "a"]
    assert len(audit.list_audit(actor="a")) == 2
    assert len(audit.list_audit(action="forbidden")) == 2


def test_log_cannot_be_changed_or_deleted(clean_db):
    audit.append_audit("a", "login", "auth")
    with pytest.raises(pg_errors.Error):
        with db.connect() as conn:
            conn.execute("UPDATE audit_log SET actor = 'evil'")
    with pytest.raises(pg_errors.Error):
        with db.connect() as conn:
            conn.execute("DELETE FROM audit_log")
    assert audit.list_audit()[0]["actor"] == "a"
