"""T11: expected outgoings (rent, payroll, tax, suppliers) typed in by the accountant, stored in PostgreSQL.

These are manual inputs. The system does not read them from Odoo, and the UI must say so.
The table is created by migrations/001_obligations.sql: run `python scripts/migrate.py` once."""
from datetime import datetime

import psycopg
import psycopg.errors

from . import db
from .forecast import Obligation


class ObligationRecord(Obligation):
    id: int
    created_by: str
    created_at: datetime


def _unavailable(action: str, e: psycopg.Error) -> db.AppDbUnavailable:
    if isinstance(e, psycopg.errors.UndefinedTable):
        return db.AppDbUnavailable(f"cannot {action}: table missing, run `python scripts/migrate.py`")
    return db.AppDbUnavailable(f"cannot {action}: {e}")


class PostgresObligations:
    """Repository over the application database."""

    def add(self, ob: Obligation, created_by: str) -> ObligationRecord:
        try:
            with db.connect() as conn:
                row = conn.execute(
                    "INSERT INTO obligations (description, amount, due_date, created_by) "
                    "VALUES (%s, %s, %s, %s) RETURNING id, description, amount, due_date, created_by, created_at",
                    (ob.description.strip(), ob.amount, ob.due_date, created_by),
                ).fetchone()
        except psycopg.Error as e:
            raise _unavailable("save obligation", e) from e
        return ObligationRecord(**row)

    def list_all(self) -> list[ObligationRecord]:
        try:
            with db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, description, amount, due_date, created_by, created_at "
                    "FROM obligations ORDER BY due_date, id"
                ).fetchall()
        except psycopg.Error as e:
            raise _unavailable("read obligations", e) from e
        return [ObligationRecord(**r) for r in rows]
