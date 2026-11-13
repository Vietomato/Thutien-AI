"""Application database (PostgreSQL): users, reminder drafts, tasks, audit log.
Odoo's database is separate and read-only (see odoo_reader.py).
Supports both psycopg and pure-Python pg8000 (bypasses Windows DLL block)."""
import os
import threading
import time
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


# Opening a PostgreSQL connection costs about 60 ms and a page load opens dozens, so connections are kept and reused (psycopg
# only). A connection goes back to the pool when its `with` block ends, after a commit or rollback, so no transaction or lock
# is carried over. Idle connections are checked before reuse. APP_DB_POOL_SIZE (default 10, 0 = off) is the most idle ones kept.
_IDLE: dict[tuple, list[tuple[object, float]]] = {}
_IDLE_LOCK = threading.Lock()
_RECHECK_AFTER = 30.0


def _pool_size() -> int:
    try:
        return max(int(os.getenv("APP_DB_POOL_SIZE", "10")), 0)
    except ValueError:
        return 10


def _discard(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


class _PooledConnection:
    """A psycopg connection that goes back to the pool at the end of `with` instead of being closed."""

    def __init__(self, conn, key: tuple):
        self._conn, self._key, self._released = conn, key, False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        healthy = True
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            healthy = not self._conn.closed and self._conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        except Exception:
            healthy = False
            if exc_type is None:
                self._release(False)
                raise
        self._release(healthy)
        return False

    def close(self) -> None:
        self._release(False)

    def _release(self, healthy: bool) -> None:
        if self._released:
            return
        self._released = True
        if healthy:
            with _IDLE_LOCK:
                idle = _IDLE.setdefault(self._key, [])
                if len(idle) < _pool_size():
                    idle.append((self._conn, time.monotonic()))
                    return
        _discard(self._conn)


def _checkout(key: tuple, factory):
    if _pool_size() <= 0:
        return factory()
    while True:
        with _IDLE_LOCK:
            idle = _IDLE.get(key)
            entry = idle.pop() if idle else None
        if entry is None:
            return _PooledConnection(factory(), key)
        conn, since = entry
        try:
            if conn.closed:
                continue
            if time.monotonic() - since > _RECHECK_AFTER:      # idle for a while: make sure the server did not drop it
                conn.execute("SELECT 1")
                conn.rollback()
            return _PooledConnection(conn, key)
        except Exception:
            _discard(conn)


def pool_stats() -> dict:
    with _IDLE_LOCK:
        return {"idle": sum(len(v) for v in _IDLE.values()), "size": _pool_size()}


def close_pool() -> None:
    with _IDLE_LOCK:
        entries = [c for v in _IDLE.values() for c, _ in v]
        _IDLE.clear()
    for conn in entries:
        _discard(conn)


def connect():
    """Open a connection. Use as `with connect() as conn:` (commits on success, rolls back on error, then reuses or closes)."""
    db_url = os.getenv("APP_DB_URL") or os.getenv("DATABASE_URL")
    password = os.getenv("APP_DB_PASSWORD")

    # Option 1: Try psycopg if available
    if psycopg is not None:
        try:
            if db_url:
                return _checkout(("url", db_url),
                                 lambda: psycopg.connect(db_url, connect_timeout=10, row_factory=dict_row))
            if password:
                host, port = os.getenv("APP_DB_HOST", "localhost"), int(os.getenv("APP_DB_PORT", "5433"))
                dbname, user = os.getenv("APP_DB_NAME", "thutien_app"), os.getenv("APP_DB_USER", "thutien_app")
                return _checkout(("params", host, port, dbname, user, password),
                                 lambda: psycopg.connect(host=host, port=port, dbname=dbname, user=user, password=password,
                                                         connect_timeout=5, row_factory=dict_row))
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
