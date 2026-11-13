import logging
import os
import threading
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
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, odoo_reader
from .auth import router as auth_router
from .config import as_of_date, data_source, production_problems
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
    problems = production_problems()
    if problems:                                  # APP_ENV=production with unsafe settings: do not serve at all
        raise RuntimeError("unsafe production settings: " + "; ".join(problems))
    try:
        db.init_schema()
    except db.AppDbUnavailable as e:
        # Keep the server up so /health explains the problem; data endpoints answer 503 until the DB is back.
        log.error("app database not ready: %s", e)
    # Read the main Odoo lists in the background so the first visitor does not wait for them.
    threading.Thread(target=odoo_reader.warm_cache, daemon=True, name="warm-cache").start()
    yield
    db.close_pool()


app = FastAPI(title="ThuTien AI", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Content-Security-Policy for the web app only (the /docs page loads its own scripts from a CDN). Inline style attributes are
# used by the React components, hence 'unsafe-inline' for styles; scripts, fonts and requests stay on this origin.
APP_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
           "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith("/app"):
        response.headers.setdefault("Content-Security-Policy", APP_CSP)
    return response
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
    class _AppFiles(StaticFiles):
        """Files under assets/ carry a content hash in their name, so browsers may keep them for a year; the page itself
        (index.html) is always revalidated so a new build is picked up at once."""

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                hashed = path.replace("\\", "/").lstrip("/").startswith("assets/")      # Windows hands over assets\name.js
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if hashed else "no-cache"
            return response

    app.mount("/app", _AppFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/app/")
    def frontend_not_built():
        return JSONResponse({"detail": "Build frontend first: cd frontend && npm ci && npm run build"}, status_code=503)
