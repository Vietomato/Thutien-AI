"""Application database (PostgreSQL). Odoo's database is separate and read-only (see odoo_reader.py).

Settings come from the environment (APP_DB_*); no credentials live in the code."""
import os

import psycopg
from psycopg.rows import dict_row


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
