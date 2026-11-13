import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env if present
for _env_path in [Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"]:
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import db, odoo_reader
from .auth import router as auth_router
from .config import as_of_date, data_source
from .routes_admin import router as admin_router
from .routes_chat import router as chat_router
from .routes_data import router as data_router
from .routes_f3 import router as f3_router
from .routes_obligations import router as obligations_router
from .routes_reminders import router as reminders_router
from .routes_tasks import router as tasks_router

log = logging.getLogger("thutien")
ROOT = Path(__file__).resolve().parents[2]


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
app.include_router(data_router)
app.include_router(chat_router)
app.include_router(f3_router)
app.include_router(obligations_router)
app.include_router(reminders_router)
app.include_router(tasks_router)
app.include_router(admin_router)


@app.exception_handler(odoo_reader.OdooUnavailable)
async def _odoo_down(_: Request, exc: odoo_reader.OdooUnavailable):
    log.error("%s", exc)
    return JSONResponse({"detail": "Odoo data source unavailable"}, status_code=502)


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


@app.get("/")
def root():
    return RedirectResponse(url="/app/")


# The React app must be built with `npm run build` before FastAPI can serve it.
frontend_dist = ROOT / "frontend" / "dist"
if (frontend_dist / "index.html").is_file():
    app.mount("/app", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/app/")
    def frontend_not_built():
        return JSONResponse({"detail": "Build frontend first: cd frontend && npm ci && npm run build"}, status_code=503)
