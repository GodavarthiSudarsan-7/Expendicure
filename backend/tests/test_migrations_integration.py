"""Real end-to-end migration test. Skipped automatically when no MySQL is
reachable, so it never blocks CI but gives real coverage when a DB is present.

    pytest -m db          # run only these
    pytest                # runs them too, skipping if no DB
"""

import os

import pytest

from database import get_db_connection
from migrations_runner import run_migrations, migration_status

pytestmark = pytest.mark.db

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database",
    "migrations",
)


@pytest.fixture
def connection():
    conn = get_db_connection()
    if conn is None:
        pytest.skip("no MySQL connection available")
    yield conn
    try:
        conn.close()
    except Exception:
        pass


def _column_exists(conn, table, column):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    )
    return cur.fetchone()[0] > 0


def _table_exists(conn, table):
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    )
    return cur.fetchone()[0] > 0


def test_migrations_apply_and_are_idempotent(connection):
    run_migrations(connection, MIGRATIONS_DIR, log=lambda *a: None)

    assert _table_exists(connection, "accounts")
    assert _table_exists(connection, "recurring_transactions")
    assert _table_exists(connection, "categorization_rules")
    assert _column_exists(connection, "transactions", "direction")
    assert _column_exists(connection, "categories", "student_id")

    # Second run is a no-op.
    second = run_migrations(connection, MIGRATIONS_DIR, log=lambda *a: None)
    assert second == []

    # Everything shows as applied.
    assert all(applied for _, applied in migration_status(connection, MIGRATIONS_DIR))
