"""Database migrations: numbered SQL files in backend/migrations/, applied once each, in order.

    python scripts/migrate.py

Each file runs in its own transaction together with its bookkeeping row, so a failing file leaves nothing
half-applied. Applied files are recorded in schema_migrations with a checksum: editing a file that is
already applied is an error. To change the schema, add a new numbered file instead."""
import hashlib
import re
from pathlib import Path

from . import db

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
NAME = re.compile(r"^\d{3,}_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    pass


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    files = sorted(directory.glob("*.sql"))
    bad = [f.name for f in files if not NAME.match(f.name)]
    if bad:
        raise MigrationError(f"bad migration file name (expected 001_name.sql): {', '.join(bad)}")
    return files


def _read(path: Path) -> tuple[str, str]:
    sql = path.read_text(encoding="utf-8").replace("\r\n", "\n")   # same checksum on Windows and Linux
    return sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()


def apply_all(directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration not applied yet. Returns the versions applied by this call."""
    files = migration_files(directory)
    with db.connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations ("
                     "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
                     "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
    ran = []
    for f in files:
        sql, checksum = _read(f)
        if f.stem in applied:
            if applied[f.stem] != checksum:
                raise MigrationError(f"{f.name} was changed after it was applied; add a new migration instead")
            continue
        with db.connect() as conn:
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)", (f.stem, checksum))
        ran.append(f.stem)
    return ran
