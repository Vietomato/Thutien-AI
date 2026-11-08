from datetime import date
import pytest
from pydantic import ValidationError
from app.contracts import Invoice


def test_invoice_valid():
    i = Invoice(invoice_id="INV-001", customer_id="C001", display_name="A",
                due_date=date(2026, 11, 1), invoice_amount=100, remaining_amount=40)
    assert i.currency == "VND" and i.dispute_status == "none"


def test_invoice_rejects_bad_dispute_status():
    with pytest.raises(ValidationError):
        Invoice(invoice_id="INV-001", customer_id="C001", display_name="A",
                due_date=date(2026, 11, 1), invoice_amount=100, remaining_amount=40,
                dispute_status="maybe")