"""Expected outgoings typed in by the accountant (rent, payroll, tax, ...), stored in PostgreSQL.

They add to the supplier bills read from Odoo: the F4 forecast compares receipts with both. The table is
created by schema.sql, like the other application tables."""
from .db import connect

_SELECT = ("SELECT o.id, o.description, o.amount, o.currency, o.due_date, o.created_by, u.username AS created_by_username, "
           "o.created_at FROM obligations o JOIN users u ON u.id = o.created_by")


def _row(r: dict) -> dict:
    r = dict(r)
    r["due_date"] = r["due_date"].isoformat()
    r["created_at"] = r["created_at"].isoformat()
    return r


def create(description: str, amount: int, due_date, created_by: int) -> dict:
    with connect() as conn:
        new_id = conn.execute(
            "INSERT INTO obligations (description, amount, due_date, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
            (description.strip(), amount, due_date, created_by),
        ).fetchone()["id"]
    return get(new_id)  # type: ignore[return-value]


def get(obligation_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(f"{_SELECT} WHERE o.id = %s", (obligation_id,)).fetchone()
    return _row(row) if row else None


def list_all() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"{_SELECT} ORDER BY o.due_date, o.id").fetchall()
    return [_row(r) for r in rows]
