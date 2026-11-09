import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db, odoo_reader
from .auth import router as auth_router
from .config import as_of_date, data_source
from .routes_admin import router as admin_router

log = logging.getLogger("thutien")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        db.init_schema()
    except db.AppDbUnavailable as e:
        # Keep the server up so /health explains the problem; data endpoints answer 503 until the DB is back.
        log.error("app database not ready: %s", e)
    yield


app = FastAPI(title="ThuTien AI", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)


@app.exception_handler(odoo_reader.OdooUnavailable)
async def _odoo_down(_: Request, exc: odoo_reader.OdooUnavailable):
    log.error("%s", exc)
    return JSONResponse({"detail": "Odoo database unavailable"}, status_code=502)


@app.exception_handler(db.AppDbUnavailable)
async def _app_db_down(_: Request, exc: db.AppDbUnavailable):
    log.error("%s", exc)
    return JSONResponse({"detail": "application database unavailable"}, status_code=503)


@app.get("/health")
def health():
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        app_db = "ok"
    except db.AppDbUnavailable:
        app_db = "unavailable"
    return {"status": "ok" if app_db == "ok" else "degraded", "data_source": data_source(),
            "as_of_date": as_of_date().isoformat(), "app_db": app_db}
