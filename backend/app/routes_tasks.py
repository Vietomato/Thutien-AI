"""Collection tasks. A chief accountant assigns invoices to the accountants they supervise
(or to themselves) and can see their team's tasks. An accountant sees and completes only their own."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import odoo_reader, tasks, users
from .audit import append_audit
from .auth import require_any_permission, require_permission
from .permissions import has_permission

router = APIRouter(prefix="/api", tags=["tasks"])


def _team_ids(user: dict) -> list[int]:
    return [m["id"] for m in users.team_of(user["id"])]


class NewTask(BaseModel):
    invoice_id: str
    assignee_id: int
    note: str | None = Field(default=None, max_length=500)


class TaskStatus(BaseModel):
    status: Literal["open", "done"]


@router.get("/team", dependencies=[Depends(require_permission("task:read_team"))])
def team(user: dict = Depends(require_permission("task:read_team"))):
    """People a chief accountant can assign work to: their team, plus themselves."""
    members = [{"id": user["id"], "username": user["username"], "full_name": user["full_name"], "is_self": True}]
    members += [{"id": m["id"], "username": m["username"], "full_name": m["full_name"], "is_self": False}
                for m in users.team_of(user["id"])]
    return {"items": members}


@router.get("/tasks")
def list_tasks(scope: Literal["mine", "team"] = "mine", status: Literal["open", "done"] | None = None,
               user: dict = Depends(require_any_permission("task:read_own", "task:read_team"))):
    if scope == "team":
        if not has_permission(user["role"], "task:read_team"):
            raise HTTPException(403, "role not allowed")
        ids = _team_ids(user)
    else:
        ids = [user["id"]]
    return {"scope": scope, "items": tasks.list_for(ids, status) if ids else []}


@router.post("/tasks", status_code=201)
def assign_task(body: NewTask, user: dict = Depends(require_permission("task:assign"))):
    if body.assignee_id not in [user["id"], *_team_ids(user)]:
        raise HTTPException(403, "assignee is not in your team")
    inv = odoo_reader.open_invoice(body.invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found or already paid")
    t = tasks.create(inv.invoice_id, inv.display_name, f"Thu nợ {inv.invoice_id} · {inv.display_name}",
                     body.note, body.assignee_id, user["id"])
    append_audit(user["username"], "assign_task", inv.invoice_id, {"task_id": t["id"], "assignee": t["assignee_username"]})
    return t


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskStatus, user: dict = Depends(require_permission("task:update"))):
    t = tasks.get(task_id)
    allowed = t is not None and (
        t["assignee_id"] == user["id"]
        or (has_permission(user["role"], "task:read_team") and t["assignee_id"] in _team_ids(user)))
    if not allowed:
        raise HTTPException(404, "task not found")  # same answer whether it exists or is out of scope
    updated = tasks.set_status(task_id, body.status)
    append_audit(user["username"], "update_task", t["invoice_id"], {"task_id": task_id, "status": body.status})
    return updated
