"""Apply database migrations (backend/migrations/*.sql) to the application database.

    python scripts/migrate.py

Needs the APP_DB_* settings in your terminal (see .env.example). Safe to run again: applied files are skipped."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import db, migrate  # noqa: E402

try:
    ran = migrate.apply_all()
except (db.AppDbUnavailable, migrate.MigrationError) as e:
    sys.exit(f"migration failed: {e}")
print("applied: " + ", ".join(ran) if ran else "database is up to date")
