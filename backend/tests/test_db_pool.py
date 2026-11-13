"""Connection pool for the application database: reuse without carrying over a transaction, a lock or a stale connection."""
import pytest

from app import db


@pytest.fixture
def pool(clean_db):
    db.close_pool()
    yield
    db.close_pool()


def backend_pid(conn) -> int:
    return conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]


def test_a_connection_is_reused_after_its_with_block(pool):
    with db.connect() as first:
        pid = backend_pid(first)
    assert db.pool_stats()["idle"] == 1
    with db.connect() as second:
        assert backend_pid(second) == pid
    assert db.pool_stats()["idle"] == 1


def test_reuse_does_not_carry_over_an_uncommitted_change(pool):
    with db.connect() as conn:
        conn.execute("INSERT INTO obligations (description, amount, due_date, created_by) "
                     "SELECT 'x', 1, current_date, id FROM (SELECT 1 AS id) s WHERE false")
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute("CREATE TEMP TABLE pool_probe (n int)")
            conn.execute("INSERT INTO pool_probe VALUES (1)")
            raise RuntimeError("boom")
    with db.connect() as conn:                                # the rolled-back temp table must not exist any more
        exists = conn.execute("SELECT to_regclass('pg_temp.pool_probe') AS t").fetchone()["t"]
        assert exists is None


def test_committed_work_is_visible_to_the_next_connection(pool):
    with db.connect() as conn:
        conn.execute("INSERT INTO users (username, full_name, password_hash, role) VALUES ('pool1', 'Pool', 'x', 'customer')")
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM users WHERE username = 'pool1'").fetchone()["n"] == 1


def test_a_closed_connection_is_not_handed_out_again(pool):
    with db.connect() as conn:
        pass
    db._IDLE[next(iter(db._IDLE))][0][0].close()              # the server (or a firewall) dropped it
    with db.connect() as conn:
        assert backend_pid(conn)                              # a fresh one was opened instead


def test_a_connection_idle_for_long_is_checked_and_replaced_when_dead(pool, monkeypatch):
    with db.connect() as conn:
        pid = backend_pid(conn)
    key = next(iter(db._IDLE))
    raw, since = db._IDLE[key][0]
    db._IDLE[key][0] = (raw, since - 1000)                    # looks idle for a long time
    with monkeypatch.context() as m:                          # an unpooled connection ends the idle one's session on the server
        m.setenv("APP_DB_POOL_SIZE", "0")
        with db.connect() as killer:
            killer.execute("SELECT pg_terminate_backend(%s)", (pid,))
    with db.connect() as conn:
        assert backend_pid(conn) != pid


def test_the_pool_is_capped(pool, monkeypatch):
    monkeypatch.setenv("APP_DB_POOL_SIZE", "2")
    conns = [db.connect() for _ in range(4)]
    for c in conns:
        c.__exit__(None, None, None)
    assert db.pool_stats() == {"idle": 2, "size": 2}


def test_pool_off_opens_and_closes_every_time(pool, monkeypatch):
    monkeypatch.setenv("APP_DB_POOL_SIZE", "0")
    with db.connect() as conn:
        first = backend_pid(conn)
    assert db.pool_stats()["idle"] == 0
    with db.connect() as conn:
        assert backend_pid(conn) != first


def test_a_different_database_setting_gets_its_own_pool(pool, monkeypatch):
    with db.connect():
        pass
    monkeypatch.setenv("APP_DB_NAME", "postgres")
    try:
        with db.connect() as conn:
            assert conn.execute("SELECT current_database() AS d").fetchone()["d"] != "thutien_test"
    except Exception:
        pytest.skip("cannot open the postgres database with the app role")
    finally:
        monkeypatch.setenv("APP_DB_NAME", "thutien_test")


def test_the_with_statement_still_returns_the_value_of_execute(pool):
    with db.connect() as conn:
        row = conn.execute("SELECT 41 + 1 AS answer").fetchone()
    assert row["answer"] == 42
