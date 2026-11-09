import os
from datetime import date


def as_of_date() -> date:
    """Calculation date. Fixed by env so results are reproducible for the demo data."""
    return date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-09"))


def data_source() -> str:
    """Business data always comes from Odoo (read-only). There is no fixture mode at runtime."""
    return "odoo"
