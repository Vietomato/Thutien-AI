"""Authentication (JWT) and authorization dependencies.

The token only carries the user id. Role, active flag and customer link are loaded from the database on
every request, so a role change or a deactivation takes effect immediately."""
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import users
from .audit import append_audit
from .config import DEFAULT_JWT_SECRET, registration_open
from .permissions import CUSTOMER, has_permission, permissions_of
from .security import DUMMY_HASH, MIN_PASSWORD_LENGTH, verify_password

bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _secret() -> str:
    return os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)


# ---------- dependencies ----------

def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if creds is None:
        raise HTTPException(401, "missing token")
    try:
        payload = jwt.decode(creds.credentials, _secret(), algorithms=["HS256"])
        user_id = int(payload["uid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "invalid or expired token")
    user = users.get_by_id(user_id)
    if user is None or not user["is_active"]:
        raise HTTPException(401, "account unavailable")
    return user


def require_permission(*needed: str):
    """Allow the request when the user's role has ALL of the given permissions."""
    def checker(user: dict = Depends(current_user)) -> dict:
        if not all(has_permission(user["role"], p) for p in needed):
            append_audit(user["username"], "forbidden", "api", {"role": user["role"], "needs": list(needed)})
            raise HTTPException(403, "role not allowed")
        return user
    return checker


def require_any_permission(*options: str):
    """Allow the request when the user's role has AT LEAST ONE of the given permissions."""
    def checker(user: dict = Depends(current_user)) -> dict:
        if not any(has_permission(user["role"], p) for p in options):
            append_audit(user["username"], "forbidden", "api", {"role": user["role"], "needs_any": list(options)})
            raise HTTPException(403, "role not allowed")
        return user
    return checker


# ---------- schemas ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    full_name: str = Field(min_length=1, max_length=100)
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _profile(user: dict) -> dict:
    return {
        "username": user["username"], "full_name": user["full_name"], "role": user["role"],
        "customer_id": user["customer_id"], "permissions": sorted(permissions_of(user["role"])),
    }


# ---------- endpoints ----------

@router.post("/login")
def login(body: LoginRequest):
    record = users.get_auth_record(body.username)
    now = datetime.now(timezone.utc)
    if record is None:
        verify_password(body.password, DUMMY_HASH)  # same cost whether or not the user exists
        append_audit(body.username[:64], "login_failed", "auth", {"reason": "unknown_user"})
        raise HTTPException(401, "invalid username or password")
    if record["locked_until"] and record["locked_until"] > now:
        append_audit(record["username"], "login_blocked", "auth", {"reason": "locked"})
        raise HTTPException(429, "too many failed attempts, try again later")
    if not verify_password(body.password, record["password_hash"]) or not record["is_active"]:
        locked = users.record_login_failure(record["id"])
        append_audit(record["username"], "login_failed", "auth", {"locked": locked})
        raise HTTPException(401, "invalid username or password")
    users.record_login_success(record["id"])
    user = users.get_by_id(record["id"])
    token = jwt.encode(
        {"uid": user["id"], "sub": user["username"], "exp": now + timedelta(hours=8)}, _secret(), algorithm="HS256")
    append_audit(user["username"], "login", "auth")
    return {"access_token": token, "token_type": "bearer", **_profile(user)}


@router.post("/register", status_code=201)
def register(body: RegisterRequest):
    """Self-registration. The account is a 'customer' not yet linked to any Odoo customer, so it sees no
    data until an admin links it or changes the role."""
    if not registration_open():
        raise HTTPException(403, "self-registration is closed; ask an administrator for an account")
    username = users.normalize_username(body.username)
    if not users.valid_username(username):
        raise HTTPException(422, "username must be 3-32 characters: a-z, 0-9, dot, dash, underscore")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if users.get_by_username(username):
        raise HTTPException(409, "username already taken")
    user = users.create_user(username, body.full_name, body.password, CUSTOMER)
    append_audit(username, "register", "account", {"role": CUSTOMER})
    return _profile(user)


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return _profile(user)


@router.post("/logout")
def logout(user: dict = Depends(current_user)):
    """Tokens are stateless; this records the logout in the audit log. The client discards the token."""
    append_audit(user["username"], "logout", "auth")
    return {"status": "ok"}


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(current_user)):
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    stored = users.get_password_hash(user["id"])
    if not stored or not verify_password(body.old_password, stored):
        append_audit(user["username"], "change_password_failed", "account")
        raise HTTPException(400, "old password is incorrect")
    users.set_password(user["id"], body.new_password)
    append_audit(user["username"], "change_password", "account")
    return {"status": "ok"}
