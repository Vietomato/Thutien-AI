"""Where business data comes from: fixtures (default) or Odoo, read-only. Shared by the API routes."""
import json
from pathlib import Path

from fastapi import HTTPException

from . import odoo_reader
from .config import data_source
from .contracts import Invoice, Payment

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_invoices_and_payments() -> tuple[list[Invoice], list[Payment]]:
    """Every invoice (paid ones too: history needs them) and every payment."""
    if data_source() == "odoo":
        try:
            return odoo_reader.all_invoices(), odoo_reader.payment_history()
        except odoo_reader.OdooUnavailable as e:
            raise HTTPException(502, str(e))
    return ([Invoice(**x) for x in fixture("invoices.json")],
            [Payment(**x) for x in fixture("payments.json")])
