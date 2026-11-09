"""Round trip through a real PostgreSQL. Opt in with a throwaway database:

    APP_DB_NAME=thutien_test APP_DB_PASSWORD=<password> pytest backend/tests/test_obligations_db.py

The test empties the obligations table, so it refuses to run on any database not named thutien_test."""
import os
from datetime import date

import pytest

from app import db, migrate
from app.forecast import Obligation
from app.obligations import PostgresObligations

pytestmark = pytest.mark.skipif(
    os.getenv("APP_DB_NAME") != "thutien_test" or not os.getenv("APP_DB_PASSWORD"),
    reason="needs APP_DB_NAME=thutien_test and APP_DB_PASSWORD",
)


@pytest.fixture
def repo():
    migrate.apply_all()
    with db.connect() as conn:
        conn.execute("TRUNCATE obligations RESTART IDENTITY")
    return PostgresObligations()


def test_saved_expenses_survive_a_new_connection_and_are_sorted_by_date(repo):
    repo.add(Obligation(description="Luong", amount=90_000_000, due_date=date(2026, 11, 25)), "accountant1")
    repo.add(Obligation(description="  Thue  ", amount=70_000_000, due_date=date(2026, 11, 12)), "accountant1")
    rows = PostgresObligations().list_all()              # a fresh repository, as after a restart
    assert [r.description for r in rows] == ["Thue", "Luong"]
    assert rows[0].amount == 70_000_000 and rows[0].created_by == "accountant1"


def test_the_database_itself_rejects_a_non_positive_amount(repo):
    with pytest.raises(Exception):
        with db.connect() as conn:
            conn.execute("INSERT INTO obligations (description, amount, due_date, created_by) "
                         "VALUES ('x', 0, '2026-11-12', 'u')")
