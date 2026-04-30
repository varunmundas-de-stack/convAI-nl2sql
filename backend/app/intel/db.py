"""
Intel DB Helper — Shared database connection for the intel scheduler.

Reuses the same DSN config as metadata_store.py so all intel queries
go to the same PostgreSQL instance without duplicating env-var logic.
"""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras


def _dsn() -> dict:
    return {
        "host": os.getenv("DB_HOST", os.getenv("POSTGRES_HOST", "localhost")),
        "port": int(os.getenv("DB_PORT", os.getenv("POSTGRES_PORT", "5432"))),
        "dbname": os.getenv("DB_NAME", os.getenv("POSTGRES_DB", "sales_analytics")),
        "user": os.getenv("DB_USER", os.getenv("POSTGRES_USER", "postgres")),
        "password": os.getenv("DB_PASS", os.getenv("POSTGRES_PASSWORD", "postgres")),
    }


@contextmanager
def get_conn():
    """Yield a psycopg2 connection with auto-commit/rollback/close."""
    conn = psycopg2.connect(**_dsn())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_cursor(conn):
    """Return a RealDictCursor for easy row-as-dict access."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
