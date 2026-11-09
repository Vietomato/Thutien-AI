import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.audit import append_audit

# username -> role. Four demo accounts, one per role.
USERS = {
    "accountant1": "accountant",
    "manager1": "manager",
    "viewer1": "viewer",
    "admin1": "admin",
}

bearer = HTTPBearer(auto_error=False)
router = APIRouter()


def _secret() -> str:
    return os.getenv("JWT_SECRET", "dev-only-secret-change-me-at-least-32-bytes")


def _demo_password() -> str:
    return os.getenv("DEMO_PASSWORD", "demo123")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
def login(body: LoginRequest):
    role = USERS.get(body.username)
    ok = role is not None and hmac.compare_digest(body.password, _demo_password())
    if not ok:
        append_audit(body.username, "login_failed", "auth")
        raise HTTPException(status_code=401, detail="invalid username or password")
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode({"sub": body.username, "role": role, "exp": exp}, _secret(), algorithm="HS256")
    append_audit(body.username, "login", "auth")
    return {"access_token": token, "token_type": "bearer", "role": role}


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if creds is None:
        raise HTTPException(status_code=401, detail="missing token")
    try:
        payload = jwt.decode(creds.credentials, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return {"username": payload["sub"], "role": payload["role"]}


def require_roles(*allowed: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in allowed:
            append_audit(user["username"], "forbidden", "api", {"role": user["role"]})
            raise HTTPException(status_code=403, detail="role not allowed")
        return user

    return checker