"""Collection tasks: a chief accountant assigns an overdue invoice to an accountant on their team."""
from .db import connect

_SELECT = ("SELECT t.id, t.invoice_id, t.customer_name, t.title, t.note, t.assignee_id, a.username AS assignee_username, "
           "a.full_name AS assignee_name, t.created_by, c.username AS created_by_username, t.status, t.created_at, t.done_at "
           "FROM tasks t JOIN users a ON a.id = t.assignee_id JOIN users c ON c.id = t.created_by")


def _row(r: dict) -> dict:
    r = dict(r)
    for k in ("created_at", "done_at"):
        if r.get(k):
            r[k] = r[k].isoformat()
    return r


def create(invoice_id: str, customer_name: str, title: str, note: str | None, assignee_id: int, created_by: int) -> dict:
    with connect() as conn:
        new_id = conn.execute(
            "INSERT INTO tasks (invoice_id, customer_name, title, note, assignee_id, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (invoice_id, customer_name, title, note, assignee_id, created_by)
        ).fetchone()["id"]
    return get(new_id)  # type: ignore[return-value]


def get(task_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(f"{_SELECT} WHERE t.id = %s", (task_id,)).fetchone()
    return _row(row) if row else None


def list_for(assignee_ids: list[int], status: str | None = None) -> list[dict]:
    sql = f"{_SELECT} WHERE t.assignee_id = ANY(%s)"
    params: list = [assignee_ids]
    if status:
        sql += " AND t.status = %s"
        params.append(status)
    sql += " ORDER BY (t.status = 'open') DESC, t.created_at DESC"
    with connect() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


def set_status(task_id: int, status: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "UPDATE tasks SET status = %s, done_at = CASE WHEN %s = 'done' THEN now() ELSE NULL END "
            "WHERE id = %s RETURNING id", (status, status, task_id)).fetchone()
    return get(row["id"]) if row else None
