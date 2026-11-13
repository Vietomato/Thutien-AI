import os
from datetime import date


def as_of_date() -> date:
    """Calculation date. Fixed by env so results are reproducible for the demo data."""
    return date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-09"))


def data_source() -> str:
    """Report the selected live Odoo source; there is no runtime fixture mode."""
    return "odoo_online" if os.getenv("ODOO_SOURCE", "local_db").strip().lower() == "online" else "odoo"


DEFAULT_JWT_SECRET = "dev-only-secret-change-me-at-least-32-bytes"


def registration_open() -> bool:
    """Self-registration is on unless ALLOW_REGISTRATION=0 (a public deployment usually does not want it)."""
    return os.getenv("ALLOW_REGISTRATION", "1").strip() != "0"


def production_problems(env=None) -> list[str]:
    """What is unsafe in the settings when APP_ENV=production (an empty list otherwise or when all is fine).
    The server refuses to start with any of these: a known signing secret lets anyone forge a login."""
    env = os.environ if env is None else env
    if (env.get("APP_ENV") or "").strip().lower() != "production":
        return []
    problems = []
    secret = env.get("JWT_SECRET", "")
    if not secret or secret == DEFAULT_JWT_SECRET:
        problems.append("JWT_SECRET is missing or is the public development default")
    elif len(secret) < 32:
        problems.append("JWT_SECRET must be at least 32 characters")
    if (env.get("APP_DB_PASSWORD") or "") in ("", "change-me") and not (env.get("APP_DB_URL") or env.get("DATABASE_URL")):
        problems.append("APP_DB_PASSWORD is missing or is the example value")
    return problems
