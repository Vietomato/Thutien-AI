import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends
from .config import as_of_date, data_source
from .contracts import Invoice, Payment
from app.auth import router as auth_router, require_roles
from . import odoo_reader, prediction

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
app = FastAPI(title="ThuTien AI")
app.include_router(auth_router)


def _fixture(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _envelope(items):
    return {"source": data_source(), "as_of_date": as_of_date().isoformat(), "items": items}


@app.get("/health")
def health():
    return {"status": "ok", "data_source": data_source(), "as_of_date": as_of_date().isoformat()}


@app.get("/api/invoices/open", dependencies=[Depends(require_roles("accountant", "manager"))])
def invoices_open():
    if data_source() == "odoo":
        try:
            items = odoo_reader.open_invoices()
        except odoo_reader.OdooUnavailable as e:
            raise HTTPException(502, str(e))
    else:
        items = [Invoice(**x) for x in _fixture("invoices.json") if x["remaining_amount"] > 0]
    return _envelope([i.model_dump(mode="json") for i in items])


@app.get("/api/predictions", dependencies=[Depends(require_roles("accountant", "manager"))])
def predictions():
    """Predicted payment dates (P25/P50/P75) for every open invoice. Computed by app.prediction."""
    if data_source() == "odoo":
        try:
            invoices, payments = odoo_reader.all_invoices(), odoo_reader.payment_history()
        except odoo_reader.OdooUnavailable as e:
            raise HTTPException(502, str(e))
    else:
        invoices = [Invoice(**x) for x in _fixture("invoices.json")]
        payments = [Payment(**x) for x in _fixture("payments.json")]
    open_invoices = [i for i in invoices if i.remaining_amount > 0]
    items = prediction.predict(open_invoices, invoices, payments, as_of_date())
    return _envelope([p.model_dump(mode="json") for p in items])


@app.get("/api/payments/history", dependencies=[Depends(require_roles("accountant", "manager"))])
def payments_history():
    if data_source() == "odoo":
        try:
            items = odoo_reader.payment_history()
        except odoo_reader.OdooUnavailable as e:
            raise HTTPException(502, str(e))
    else:
        items = [Payment(**x) for x in _fixture("payments.json")]
    return _envelope([p.model_dump(mode="json") for p in items])