import os
from datetime import date

def as_of_date() -> date:
    return date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-09"))

def data_source() -> str:
    return os.getenv("DATA_SOURCE", "fixture")


def odoo_mode() -> str:
    """How Odoo is read when DATA_SOURCE=odoo: 'sql' (PostgreSQL directly, default) or 'api' (hosted Odoo)."""
    mode = os.getenv("ODOO_MODE", "sql").strip().lower()
    if mode not in ("sql", "api"):
        raise ValueError(f"ODOO_MODE must be 'sql' or 'api', got {mode!r}")
    return mode
