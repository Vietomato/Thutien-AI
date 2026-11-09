"""Load demo expected outgoings (about a dozen, one of them large enough to trigger a shortfall alert).

    python scripts/migrate.py          # once, creates the tables
    python scripts/seed_obligations.py

Safe to run again: outgoings already loaded are skipped. The data is simulated (made-up company)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import db  # noqa: E402
from app.demo_data import seed_demo_obligations  # noqa: E402
from app.obligations import PostgresObligations  # noqa: E402

try:
    added = seed_demo_obligations(PostgresObligations())
except db.AppDbUnavailable as e:
    sys.exit(f"seed failed: {e}")
print(f"added {added} demo outgoings" if added else "demo outgoings already loaded")
