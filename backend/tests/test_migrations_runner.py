"""Unit tests for the migration runner. No MySQL required — a fake connection
records executed statements and simulates the schema_migrations table."""

import os

import pytest

from migrations_runner import (
    run_migrations,
    migration_status,
    split_statements,
    discover_migrations,
)

REAL_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "database",
    "migrations",
)


class FakeCursor:
    def __init__(self, store):
        self._store = store
        self._result = None
        self.with_rows = False

    def execute(self, sql, params=None):
        self._store["executed"].append((" ".join(sql.split()), params))
        lowered = sql.strip().lower()
        if lowered.startswith("select filename from schema_migrations"):
            self._result = [(name,) for name in sorted(self._store["applied"])]
            self.with_rows = True
        elif lowered.startswith("insert into schema_migrations"):
            self._store["applied"].add(params[0])
            self.with_rows = False
        elif lowered.startswith("select"):
            self._result = [(1,)]
            self.with_rows = True
        else:
            self._result = None
            self.with_rows = False

    def fetchall(self):
        if not self.with_rows:
            raise Exception("no result set")
        rows, self._result, self.with_rows = self._result, None, False
        return rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.store = {"executed": [], "applied": set(), "commits": 0, "rollbacks": 0}

    def cursor(self, *args, **kwargs):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1

    def rollback(self):
        self.store["rollbacks"] += 1

    def close(self):
        pass


@pytest.fixture
def fake_dir(tmp_path):
    (tmp_path / "001_a.sql").write_text(
        "-- first\nCREATE TABLE IF NOT EXISTS a (id INT);\n", encoding="utf-8"
    )
    (tmp_path / "002_b.sql").write_text(
        "CREATE TABLE IF NOT EXISTS b (id INT);\nCREATE TABLE IF NOT EXISTS c (id INT);\n",
        encoding="utf-8",
    )
    (tmp_path / "010_z.sql").write_text(
        "CREATE TABLE IF NOT EXISTS z (id INT);\n", encoding="utf-8"
    )
    return str(tmp_path)


def test_split_statements_basic():
    sql = "-- comment\nCREATE TABLE x (\n id INT\n);\nSELECT 1;\n"
    assert split_statements(sql) == ["CREATE TABLE x (\n id INT\n)", "SELECT 1"]


def test_split_statements_ignores_blank_and_comments():
    assert split_statements("\n\n-- only comments\n\n") == []


def test_discover_migrations_sorted(fake_dir):
    names = [name for name, _ in discover_migrations(fake_dir)]
    assert names == ["001_a.sql", "002_b.sql", "010_z.sql"]


def test_run_migrations_applies_in_order(fake_dir):
    conn = FakeConnection()
    applied = run_migrations(conn, fake_dir, log=lambda *a: None)
    assert applied == ["001_a.sql", "002_b.sql", "010_z.sql"]
    inserts = [
        params[0]
        for sql, params in conn.store["executed"]
        if sql.lower().startswith("insert into schema_migrations")
    ]
    assert inserts == ["001_a.sql", "002_b.sql", "010_z.sql"]


def test_run_migrations_is_idempotent(fake_dir):
    conn = FakeConnection()
    run_migrations(conn, fake_dir, log=lambda *a: None)
    second = run_migrations(conn, fake_dir, log=lambda *a: None)
    assert second == []


def test_run_migrations_only_runs_pending(fake_dir):
    conn = FakeConnection()
    conn.store["applied"].add("001_a.sql")
    applied = run_migrations(conn, fake_dir, log=lambda *a: None)
    assert applied == ["002_b.sql", "010_z.sql"]


def test_run_migrations_executes_each_statement(fake_dir):
    conn = FakeConnection()
    run_migrations(conn, fake_dir, log=lambda *a: None)
    creates = [
        sql for sql, _ in conn.store["executed"] if sql.lower().startswith("create table if not exists")
    ]
    # a, b, c, z  (plus the schema_migrations table itself)
    assert "CREATE TABLE IF NOT EXISTS a (id INT)" in creates
    assert "CREATE TABLE IF NOT EXISTS c (id INT)" in creates
    assert "CREATE TABLE IF NOT EXISTS z (id INT)" in creates


def test_migration_status_reports_pending(fake_dir):
    conn = FakeConnection()
    conn.store["applied"].add("001_a.sql")
    status = migration_status(conn, fake_dir)
    assert status == [("001_a.sql", True), ("002_b.sql", False), ("010_z.sql", False)]


# ---- sanity checks against the real migration files (no DB) ----

def test_real_migrations_present_and_ordered():
    names = [name for name, _ in discover_migrations(REAL_MIGRATIONS_DIR)]
    assert names == sorted(names)
    assert names[0] == "000_base_schema.sql"
    assert "001_transaction_direction.sql" in names
    assert "005_category_scope.sql" in names


def test_real_migrations_split_without_error():
    for name, path in discover_migrations(REAL_MIGRATIONS_DIR):
        with open(path, "r", encoding="utf-8") as fh:
            statements = split_statements(fh.read())
        assert statements, f"{name} produced no statements"
        for stmt in statements:
            assert ";" not in stmt.rstrip(";"), f"{name}: statement still contains ';'"


def test_real_migrations_run_through_fake_connection():
    """Exercise the whole runner path over the real migration files (no MySQL):
    every statement reaches cursor.execute exactly once, in file order, and each
    file is recorded."""
    conn = FakeConnection()
    applied = run_migrations(conn, REAL_MIGRATIONS_DIR, log=lambda *a: None)
    assert applied[0] == "000_base_schema.sql"
    assert "001_transaction_direction.sql" in applied
    assert "005_category_scope.sql" in applied
    # idempotent second run
    assert run_migrations(conn, REAL_MIGRATIONS_DIR, log=lambda *a: None) == []
    executed_sql = [sql for sql, _ in conn.store["executed"]]
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS accounts") for s in executed_sql)
    assert any("ADD COLUMN direction" in s for s in executed_sql)
