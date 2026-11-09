"""Admin: user management, role assignment, audit log. No financial data is reachable from here."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg import errors as pg_errors

from . import odoo_reader, users
from .audit import append_audit, list_audit
from .auth import require_permission
from .permissions import ACCOUNTANT, ADMIN, CHIEF, CUSTOMER, ROLES
from .security import MIN_PASSWORD_LENGTH

router = APIRouter(prefix="/api/admin", tags=["admin"])


class NewUser(BaseModel):
    username: str
    full_name: str = Field(min_length=1, max_length=100)
    password: str
    role: str
    customer_id: str | None = None
    supervisor_id: int | None = None


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = None
    customer_id: str | None = None
    supervisor_id: int | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str


def _check_assignment(role: str, customer_id: str | None, supervisor_id: int | None) -> None:
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {', '.join(ROLES)}")
    if customer_id:
        if role != CUSTOMER:
            raise HTTPException(422, "only a customer account can be linked to an Odoo customer")
        if customer_id not in {c["customer_id"] for c in odoo_reader.customers()}:
            raise HTTPException(422, "unknown Odoo customer id")
    if supervisor_id is not None:
        if role != ACCOUNTANT:
            raise HTTPException(422, "only an accountant has a supervisor")
        boss = users.get_by_id(supervisor_id)
        if boss is None or boss["role"] != CHIEF or not boss["is_active"]:
            raise HTTPException(422, "supervisor must be an active chief accountant")


@router.get("/users", dependencies=[Depends(require_permission("user:manage"))])
def list_users():
    return {"items": users.list_users()}


@router.get("/customers", dependencies=[Depends(require_permission("user:manage"))])
def odoo_customers():
    """Odoo customers an account can be linked to (names only, no amounts)."""
    return {"items": odoo_reader.customers()}


@router.post("/users", status_code=201)
def create_user(body: NewUser, admin: dict = Depends(require_permission("user:manage"))):
    username = users.normalize_username(body.username)
    if not users.valid_username(username):
        raise HTTPException(422, "username must be 3-32 characters: a-z, 0-9, dot, dash, underscore")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    _check_assignment(body.role, body.customer_id, body.supervisor_id)
    try:
        user = users.create_user(username, body.full_name, body.password, body.role, body.customer_id, body.supervisor_id)
    except pg_errors.UniqueViolation:
        raise HTTPException(409, "username already taken")
    append_audit(admin["username"], "create_user", username, {"role": body.role})
    return user


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, admin: dict = Depends(require_permission("user:manage"))):
    target = users.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    changes = body.model_dump(exclude_unset=True)
    role = changes.get("role", target["role"])
    if user_id == admin["id"] and (role != target["role"] or changes.get("is_active") is False):
        raise HTTPException(409, "you cannot change your own role or deactivate yourself")
    leaving_admin = target["role"] == ADMIN and (role != ADMIN or changes.get("is_active") is False)
    if leaving_admin and users.count_active_admins(excluding=user_id) < 1:
        raise HTTPException(409, "at least one active admin must remain")
    # Fields that only make sense for one role are cleared when the role changes.
    customer_id = changes.get("customer_id", target["customer_id"]) if role == CUSTOMER else None
    supervisor_id = changes.get("supervisor_id", target["supervisor_id"]) if role == ACCOUNTANT else None
    _check_assignment(role, customer_id, supervisor_id)
    new_fields = {**{k: v for k, v in changes.items() if k in ("full_name", "is_active")},
                  "role": role, "customer_id": customer_id, "supervisor_id": supervisor_id}
    if target["role"] == CHIEF and role != CHIEF:
        users.clear_team(user_id)
    updated = users.update_user(user_id, new_fields)
    if role != target["role"]:
        append_audit(admin["username"], "set_role", target["username"], {"from": target["role"], "to": role})
    other = {k: v for k, v in new_fields.items() if k != "role" and v != target.get(k)}
    if other:
        append_audit(admin["username"], "update_user", target["username"], other)
    return updated


@router.post("/users/{user_id}/password")
def reset_password(user_id: int, body: PasswordReset, admin: dict = Depends(require_permission("user:manage"))):
    target = users.get_by_id(user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    users.set_password(user_id, body.password)
    append_audit(admin["username"], "reset_password", target["username"])
    return {"status": "ok"}


@router.get("/audit", dependencies=[Depends(require_permission("audit:read"))])
def audit_log(limit: int = Query(100, ge=1, le=500), actor: str | None = None, action: str | None = None):
    return {"items": list_audit(limit, actor, action)}
