"""Migration runner. The first tests need no database; the rest run only against the throwaway thutien_test
database (same opt-in as test_obligations_db.py)."""
import os

import pytest

from app import db, migrate

needs_db = pytest.mark.skipif(
    os.getenv("APP_DB_NAME") != "thutien_test" or not os.getenv("APP_DB_PASSWORD"),
    reason="needs APP_DB_NAME=thutien_test and APP_DB_PASSWORD",
)


def test_the_real_migrations_are_numbered_and_in_order():
    names = [f.name for f in migrate.migration_files()]
    assert names and names == sorted(names)
    assert names[0] == "001_obligations.sql"


def test_files_run_in_numeric_order(tmp_path):
    for n in ("010_b.sql", "002_a.sql", "001_first.sql"):
        (tmp_path / n).write_text("SELECT 1;")
    assert [f.name for f in migrate.migration_files(tmp_path)] == ["001_first.sql", "002_a.sql", "010_b.sql"]


@pytest.mark.parametrize("bad", ["init.sql", "1_x.sql", "001-x.sql", "001_X.sql"])
def test_badly_named_files_are_rejected(tmp_path, bad):
    (tmp_path / bad).write_text("SELECT 1;")
    with pytest.raises(migrate.MigrationError):
        migrate.migration_files(tmp_path)


@pytest.fixture
def scratch():
    """Versions 9xx are used only by these tests; remove their traces afterwards."""
    yield
    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS scratch_a, scratch_b")
        conn.execute("DELETE FROM schema_migrations WHERE version LIKE '9%'")


@needs_db
def test_applies_once_then_does_nothing(tmp_path, scratch):
    (tmp_path / "901_scratch_a.sql").write_text("CREATE TABLE scratch_a (id int);")
    assert migrate.apply_all(tmp_path) == ["901_scratch_a"]
    assert migrate.apply_all(tmp_path) == []                     # second run: nothing left to do


@needs_db
def test_a_new_file_is_picked_up_later(tmp_path, scratch):
    (tmp_path / "901_scratch_a.sql").write_text("CREATE TABLE scratch_a (id int);")
    migrate.apply_all(tmp_path)
    (tmp_path / "902_scratch_b.sql").write_text("CREATE TABLE scratch_b (id int);")
    assert migrate.apply_all(tmp_path) == ["902_scratch_b"]


@needs_db
def test_editing_an_applied_file_is_an_error(tmp_path, scratch):
    f = tmp_path / "901_scratch_a.sql"
    f.write_text("CREATE TABLE scratch_a (id int);")
    migrate.apply_all(tmp_path)
    f.write_text("CREATE TABLE scratch_a (id int, extra int);")
    with pytest.raises(migrate.MigrationError):
        migrate.apply_all(tmp_path)


@needs_db
def test_line_endings_do_not_change_the_checksum(tmp_path, scratch):
    f = tmp_path / "901_scratch_a.sql"
    f.write_bytes(b"CREATE TABLE scratch_a (id int);\n")
    migrate.apply_all(tmp_path)
    f.write_bytes(b"CREATE TABLE scratch_a (id int);\r\n")       # same file checked out on Windows
    assert migrate.apply_all(tmp_path) == []


@needs_db
def test_a_failing_migration_leaves_nothing_behind(tmp_path, scratch):
    (tmp_path / "901_scratch_a.sql").write_text("CREATE TABLE scratch_a (id int);\nSELECT * FROM no_such_table;")
    with pytest.raises(Exception):
        migrate.apply_all(tmp_path)
    with db.connect() as conn:
        assert conn.execute("SELECT to_regclass('scratch_a') AS t").fetchone()["t"] is None
        assert conn.execute("SELECT count(*) AS n FROM schema_migrations WHERE version = '901_scratch_a'").fetchone()["n"] == 0
