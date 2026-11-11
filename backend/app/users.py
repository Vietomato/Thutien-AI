"""User storage (app database)."""
import re
from datetime import datetime, timedelta, timezone

from .db import connect
from .security import hash_password

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15

# Never select password_hash for anything that leaves this module except authentication.
_PUBLIC = "id, username, full_name, role, customer_id, supervisor_id, is_active, created_at"


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = dict(row)
    row.pop("password_hash", None)
    if row.get("created_at"):
        row["created_at"] = row["created_at"].isoformat()
    return row


def get_by_id(user_id: int) -> dict | None:
    with connect() as conn:
        return _public(conn.execute(f"SELECT {_PUBLIC} FROM users WHERE id = %s", (user_id,)).fetchone())


def get_by_username(username: str) -> dict | None:
    with connect() as conn:
        return _public(conn.execute(
            f"SELECT {_PUBLIC} FROM users WHERE lower(username) = %s", (normalize_username(username),)).fetchone())


def get_auth_record(username: str) -> dict | None:
    """Includes password_hash and lock state. For login only."""
    with connect() as conn:
        return conn.execute(
            "SELECT id, username, password_hash, is_active, failed_logins, locked_until "
            "FROM users WHERE lower(username) = %s", (normalize_username(username),)).fetchone()


def create_user(username: str, full_name: str, password: str, role: str,
                customer_id: str | None = None, supervisor_id: int | None = None) -> dict:
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role, customer_id, supervisor_id) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_PUBLIC}",
            (normalize_username(username), full_name.strip(), hash_password(password), role, customer_id, supervisor_id),
        ).fetchone()
        return _public(row)


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT u.id, u.username, u.full_name, u.role, u.customer_id, u.supervisor_id, u.is_active, u.created_at, "
            "s.username AS supervisor_username FROM users u LEFT JOIN users s ON s.id = u.supervisor_id "
            "ORDER BY u.id").fetchall()
    return [_public(r) for r in rows]


def team_of(chief_id: int) -> list[dict]:
    """Active accountants supervised by this chief accountant."""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {_PUBLIC} FROM users WHERE supervisor_id = %s AND is_active ORDER BY username", (chief_id,)).fetchall()
    return [_public(r) for r in rows]


_UPDATABLE = {"full_name", "role", "customer_id", "supervisor_id", "is_active"}


def update_user(user_id: int, fields: dict) -> dict | None:
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return get_by_id(user_id)
    sets = ", ".join(f"{k} = %s" for k in fields)
    with connect() as conn:
        row = conn.execute(
            f"UPDATE users SET {sets} WHERE id = %s RETURNING {_PUBLIC}", [*fields.values(), user_id]).fetchone()
        return _public(row)


def clear_team(chief_id: int) -> None:
    """Detach every accountant from this supervisor (used when the chief changes role)."""
    with connect() as conn:
        conn.execute("UPDATE users SET supervisor_id = NULL WHERE supervisor_id = %s", (chief_id,))


def set_password(user_id: int, password: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = %s, failed_logins = 0, locked_until = NULL WHERE id = %s",
            (hash_password(password), user_id))


def get_password_hash(user_id: int) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        return row["password_hash"] if row else None


def record_login_failure(user_id: int) -> bool:
    """Count a failed login. Returns True when this failure locked the account."""
    with connect() as conn:
        row = conn.execute(
            "UPDATE users SET failed_logins = failed_logins + 1, "
            "locked_until = CASE WHEN failed_logins + 1 >= %s THEN %s ELSE locked_until END "
            "WHERE id = %s RETURNING failed_logins",
            (MAX_FAILED_LOGINS, datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES), user_id)).fetchone()
        return bool(row and row["failed_logins"] >= MAX_FAILED_LOGINS)


def record_login_success(user_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s", (user_id,))


def count_active_admins(excluding: int | None = None) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM users WHERE role = 'admin' AND is_active AND id IS DISTINCT FROM %s",
            (excluding,)).fetchone()
        return row["n"]
