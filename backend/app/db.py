"""Application database (PostgreSQL): users, reminder drafts, tasks, audit log.
Odoo's database is separate and read-only (see odoo_reader.py).
Supports both psycopg and pure-Python pg8000 (bypasses Windows DLL block)."""
import os
import urllib.parse
from pathlib import Path

# Load .env if present
for _env_path in [Path(__file__).resolve().parents[2] / ".env", Path(__file__).resolve().parents[1] / ".env"]:
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

try:
    import pg8000.dbapi
except Exception:
    pg8000 = None

SCHEMA = Path(__file__).with_name("schema.sql")


class AppDbUnavailable(Exception):
    pass


class _Pg8000CursorWrapper:
    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))

    def fetchall(self):
        if not self._cur.description:
            return []
        cols = [d[0] for d in self._cur.description]
        return [dict(zip(cols, r)) for r in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount


class _Pg8000ConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _Pg8000CursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def connect():
    """Open a connection. Use as `with connect() as conn:` (commits on success, rolls back on error, closes)."""
    db_url = os.getenv("APP_DB_URL") or os.getenv("DATABASE_URL")
    password = os.getenv("APP_DB_PASSWORD")

    # Option 1: Try psycopg if available
    if psycopg is not None:
        try:
            if db_url:
                return psycopg.connect(db_url, connect_timeout=10, row_factory=dict_row)
            if password:
                return psycopg.connect(
                    host=os.getenv("APP_DB_HOST", "localhost"),
                    port=int(os.getenv("APP_DB_PORT", "5433")),
                    dbname=os.getenv("APP_DB_NAME", "thutien_app"),
                    user=os.getenv("APP_DB_USER", "thutien_app"),
                    password=password,
                    connect_timeout=5,
                    row_factory=dict_row,
                )
        except Exception:
            pass  # Fall through to pg8000

    # Option 2: Fallback to pure-Python pg8000 (never blocked by Windows DLL policy)
    if pg8000 is not None:
        try:
            if db_url:
                parsed = urllib.parse.urlparse(db_url)
                return _Pg8000ConnectionWrapper(pg8000.dbapi.connect(
                    user=parsed.username or "postgres",
                    password=parsed.password or "",
                    host=parsed.hostname or "localhost",
                    port=parsed.port or 5432,
                    database=parsed.path.lstrip("/") or "postgres",
                ))
            if not password:
                raise AppDbUnavailable("APP_DB_PASSWORD is not set")
            return _Pg8000ConnectionWrapper(pg8000.dbapi.connect(
                user=os.getenv("APP_DB_USER", "thutien_app"),
                password=password,
                host=os.getenv("APP_DB_HOST", "localhost"),
                port=int(os.getenv("APP_DB_PORT", "5433")),
                database=os.getenv("APP_DB_NAME", "thutien_app"),
            ))
        except Exception as e:
            raise AppDbUnavailable(f"cannot connect to app DB: {e}") from e

    raise AppDbUnavailable("No PostgreSQL driver available (psycopg and pg8000 both failed)")


def init_schema() -> None:
    """Create tables if missing. Safe to run on every start."""
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
