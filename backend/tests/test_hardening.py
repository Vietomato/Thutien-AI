"""Safe-by-default settings, response headers, compression and static caching."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
GOOD = {"APP_ENV": "production", "JWT_SECRET": "x" * 40, "APP_DB_PASSWORD": "a-real-password"}


# ---------------------------------------------------------------- production guard

def test_development_is_never_blocked():
    assert config.production_problems({}) == []
    assert config.production_problems({"JWT_SECRET": config.DEFAULT_JWT_SECRET}) == []


def test_production_with_good_settings_is_allowed():
    assert config.production_problems(GOOD) == []
    assert config.production_problems({"APP_ENV": "Production", "JWT_SECRET": "y" * 32, "APP_DB_URL": "postgresql://u:p@h/db"}) == []


@pytest.mark.parametrize("change,expected", [
    ({"JWT_SECRET": ""}, "JWT_SECRET"),
    ({"JWT_SECRET": config.DEFAULT_JWT_SECRET}, "JWT_SECRET"),
    ({"JWT_SECRET": "short"}, "at least 32"),
    ({"APP_DB_PASSWORD": "change-me"}, "APP_DB_PASSWORD"),
    ({"APP_DB_PASSWORD": ""}, "APP_DB_PASSWORD"),
])
def test_production_refuses_unsafe_settings(change, expected):
    problems = config.production_problems({**GOOD, **change})
    assert problems and expected in " ".join(problems)


def test_the_server_does_not_start_in_production_with_the_default_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", config.DEFAULT_JWT_SECRET)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(app):
            pass


# ---------------------------------------------------------------- registration switch

def test_registration_can_be_closed(client, monkeypatch):
    body = {"username": "newperson", "full_name": "New Person", "password": "long-enough-password"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    monkeypatch.setenv("ALLOW_REGISTRATION", "0")
    r = client.post("/api/auth/register", json={**body, "username": "another"})
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    assert config.registration_open() is False


def test_registration_is_open_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
    assert config.registration_open() is True


# ---------------------------------------------------------------- headers, compression, caching

def test_security_headers_are_on_every_response():
    r = TestClient(app).get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "strict-origin" in r.headers["referrer-policy"]


def test_docs_are_not_given_the_app_csp():
    assert "content-security-policy" not in TestClient(app).get("/docs").headers      # Swagger loads scripts from a CDN


@pytest.mark.skipif(not (DIST / "index.html").is_file(), reason="frontend not built")
def test_the_app_page_has_a_strict_csp_and_is_always_revalidated():
    r = TestClient(app).get("/app/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "fonts.googleapis" not in csp
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.skipif(not (DIST / "assets").is_dir(), reason="frontend not built")
def test_hashed_assets_are_kept_by_the_browser_for_a_year():
    asset = next((DIST / "assets").glob("*.js"))
    r = TestClient(app).get(f"/app/assets/{asset.name}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_large_answers_are_compressed():
    r = TestClient(app).get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"


def test_small_answers_are_not_compressed():
    assert "content-encoding" not in TestClient(app).get("/health", headers={"Accept-Encoding": "gzip"}).headers
