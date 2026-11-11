import os
from datetime import date


def as_of_date() -> date:
    """Calculation date. Fixed by env so results are reproducible for the demo data."""
    return date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-09"))


def data_source() -> str:
    """Report the selected live Odoo source; there is no runtime fixture mode."""
    return "odoo_online" if os.getenv("ODOO_SOURCE", "local_db").strip().lower() == "online" else "odoo"
