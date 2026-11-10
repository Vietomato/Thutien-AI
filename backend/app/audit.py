"""Append-only audit log in the app database. There is no update or delete (a DB trigger enforces it)."""
from psycopg.types.json import Jsonb

from .db import connect

SENSITIVE_KEYS = {"password", "new_password", "old_password", "token", "secret", "authorization", "api_key"}


def _clean(detail: dict | None) -> dict:
    if not detail:
        return {}
    return {k: ("***" if k.lower() in SENSITIVE_KEYS else v) for k, v in detail.items()}


def append_audit(actor: str, action: str, target: str, detail: dict | None = None, *, conn=None) -> int:
    """Append one audit record and return its id."""
    def insert(db):
        row = db.execute(
            "INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s) RETURNING id",
            (actor, action, target, Jsonb(_clean(detail))),
        ).fetchone()
        return row["id"]
    if conn is not None:
        return insert(conn)
    with connect() as own_conn:
        return insert(own_conn)


def list_draft_history(draft_id: int) -> list[dict]:
    """Audit trail for one visible draft; excludes unrelated login and admin events."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, actor, action, target, detail FROM audit_log "
            "WHERE action = ANY(%s) AND detail->>'draft_id' = %s ORDER BY id",
            (["create_draft", "edit_draft", "approve_draft", "reject_draft"], str(draft_id)),
        ).fetchall()
    return [{**r, "ts": r["ts"].isoformat()} for r in rows]


def list_audit(limit: int = 100, actor: str | None = None, action: str | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    where, params = [], []
    if actor:
        where.append("actor = %s")
        params.append(actor)
    if action:
        where.append("action = %s")
        params.append(action)
    sql = "SELECT id, ts, actor, action, target, detail FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{**r, "ts": r["ts"].isoformat()} for r in rows]
