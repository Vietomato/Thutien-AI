"""Application database (PostgreSQL): users, reminder drafts, tasks, audit log.
Odoo's database is separate and read-only (see odoo_reader.py)."""
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA = Path(__file__).with_name("schema.sql")


class AppDbUnavailable(Exception):
    pass


def connect() -> psycopg.Connection:
    """Open a connection. Use as `with connect() as conn:` (commits on success, rolls back on error, closes)."""
    password = os.getenv("APP_DB_PASSWORD")
    if not password:
        raise AppDbUnavailable("APP_DB_PASSWORD is not set")
    try:
        return psycopg.connect(
            host=os.getenv("APP_DB_HOST", "localhost"),
            port=int(os.getenv("APP_DB_PORT", "5433")),
            dbname=os.getenv("APP_DB_NAME", "thutien_app"),
            user=os.getenv("APP_DB_USER", "thutien_app"),
            password=password,
            connect_timeout=5,
            row_factory=dict_row,
        )
    except psycopg.Error as e:
        raise AppDbUnavailable(f"cannot connect to app DB: {e}") from e


def init_schema() -> None:
    """Create tables if missing. Safe to run on every start."""
    with connect() as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
