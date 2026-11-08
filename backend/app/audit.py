import json
import os
import sqlite3
from datetime import datetime, timezone

SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "api_key"}


def _db_path() -> str:
    return os.getenv("AUDIT_DB_PATH", "thutien.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            detail TEXT
        )
        """
    )
    return conn


def _clean(detail: dict | None) -> dict:
    if not detail:
        return {}
    return {
        k: ("***" if k.lower() in SENSITIVE_KEYS else v)
        for k, v in detail.items()
    }


def append_audit(actor: str, action: str, target: str, detail: dict | None = None) -> int:
    """Append one audit record. Returns its id. There is no update or delete."""
    ts = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO audit_log (ts, actor, action, target, detail) VALUES (?, ?, ?, ?, ?)",
            (ts, actor, action, target, json.dumps(_clean(detail), ensure_ascii=False)),
        )
        return cur.lastrowid


def list_audit(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, actor, action, target, detail FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "actor": r[2], "action": r[3], "target": r[4], "detail": json.loads(r[5] or "{}")}
        for r in rows
    ]