"""Create the demo accounts in the application database (one per role, plus a second accountant).

Passwords are never stored in the repo. Set DEMO_PASSWORD in your own terminal first:
    $env:DEMO_PASSWORD="..."
    $env:APP_DB_PASSWORD="..."
    python scripts/seed_users.py

Safe to run again: accounts that already exist are left alone.
The customer account is linked to Odoo customer C001; change the link later in the admin screen."""
import os
import sys
from pathlib import Path

# Load .env if present
for _env_path in [Path(__file__).resolve().parents[1] / ".env", Path(__file__).resolve().parents[1] / "backend" / ".env"]:
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import db, users  # noqa: E402
from app.permissions import ACCOUNTANT, ADMIN, CHIEF, CUSTOMER  # noqa: E402
from app.security import MIN_PASSWORD_LENGTH  # noqa: E402

password = os.environ.get("DEMO_PASSWORD", "")
if len(password) < MIN_PASSWORD_LENGTH:
    sys.exit(f"Set DEMO_PASSWORD (at least {MIN_PASSWORD_LENGTH} characters) in your terminal first.")

db.init_schema()


def ensure(username, full_name, role, **kw):
    existing = users.get_by_username(username)
    if existing:
        print(f"exists   {username}")
        return existing
    created = users.create_user(username, full_name, password, role, **kw)
    print(f"created  {username} ({role})")
    return created


chief = ensure("chief1", "Kế toán trưởng", CHIEF)
ensure("accountant1", "Nhân viên kế toán 1", ACCOUNTANT, supervisor_id=chief["id"])
ensure("accountant2", "Nhân viên kế toán 2", ACCOUNTANT, supervisor_id=chief["id"])
ensure("customer1", "Khách hàng C001", CUSTOMER, customer_id="C001")
ensure("admin1", "Quản trị viên", ADMIN)
