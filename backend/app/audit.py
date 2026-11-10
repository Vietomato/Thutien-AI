"""Append-only audit log in the app database. There is no update or delete (a DB trigger enforces it)."""
import json
try:
    from psycopg.types.json import Jsonb
except Exception:
    class Jsonb:  # type: ignore
        def __init__(self, data):
            self.data = data
        def __conform__(self, proto):
            return json.dumps(self.data)
        def __str__(self):
            return json.dumps(self.data)

from .db import connect

SENSITIVE_KEYS = {"password", "new_password", "old_password", "token", "secret", "authorization", "api_key"}


def _clean(detail: dict | None) -> dict:
    if not detail:
        return {}
    return {k: ("***" if k.lower() in SENSITIVE_KEYS else v) for k, v in detail.items()}


def append_audit(actor: str, action: str, target: str, detail: dict | None = None) -> int:
    """Append one audit record and return its id."""
    with connect() as conn:
        row = conn.execute(
            "INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s) RETURNING id",
            (actor, action, target, Jsonb(_clean(detail))),
        ).fetchone()
        return row["id"]


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
