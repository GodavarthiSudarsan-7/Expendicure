"""Minimal forward-only SQL migration runner.

Design goals (Phase 2):
- No ORM, no third-party migration framework.
- Migrations are plain ``*.sql`` files in ``database/migrations/``.
- Applied migrations are tracked in a ``schema_migrations`` table and never
  re-run.
- Files execute in ascending filename order (``000_...`` before ``001_...``).
- Each file is applied then recorded, and committed, before the next one — so a
  failure part-way through the set does not undo earlier successful files.

MySQL note: DDL statements implicitly commit in MySQL, so a *single* migration
file that fails half-way cannot be rolled back automatically. Migrations are
therefore written to be individually safe to re-run (``CREATE TABLE IF NOT
EXISTS`` and ``information_schema``-guarded ``ALTER``s).
"""

import os

MIGRATIONS_TABLE = "schema_migrations"

CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "filename VARCHAR(255) PRIMARY KEY, "
    "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
)


def discover_migrations(migrations_dir):
    """Return ``[(filename, full_path), ...]`` for ``*.sql`` files, sorted by name."""
    if not os.path.isdir(migrations_dir):
        raise FileNotFoundError(f"migrations directory not found: {migrations_dir}")
    names = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
    return [(name, os.path.join(migrations_dir, name)) for name in names]


def split_statements(sql):
    """Split a migration script into individual statements.

    Rules kept deliberately simple (our migrations contain only DDL and
    ``SET`` / ``PREPARE`` / ``EXECUTE`` helpers, no procedure bodies, no ``;``
    inside string literals):
    - lines that are blank or start with ``--`` are dropped
    - a statement ends at a line whose stripped text ends with ``;``
    """
    statements = []
    buff = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buff.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buff).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buff = []
    tail = "\n".join(buff).strip()
    if tail:
        statements.append(tail)
    return statements


def _fetch_all_if_rows(cursor):
    """Consume any pending result set so the next execute() is safe."""
    if getattr(cursor, "with_rows", False):
        try:
            cursor.fetchall()
        except Exception:
            pass


def applied_migrations(cursor):
    """Return the set of migration filenames already recorded as applied."""
    cursor.execute(f"SELECT filename FROM {MIGRATIONS_TABLE}")
    rows = cursor.fetchall()
    result = set()
    for row in rows:
        if isinstance(row, dict):
            result.add(row["filename"])
        else:
            result.add(row[0])
    return result


def run_migrations(connection, migrations_dir, log=print):
    """Apply every pending migration in ``migrations_dir``.

    Returns the list of filenames that were applied by this call (empty if the
    database was already up to date).
    """
    cursor = connection.cursor()
    cursor.execute(CREATE_TABLE_SQL)
    _fetch_all_if_rows(cursor)
    connection.commit()

    done = applied_migrations(cursor)
    newly_applied = []

    for filename, path in discover_migrations(migrations_dir):
        if filename in done:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            script = handle.read()

        log(f"Applying migration: {filename}")
        try:
            for statement in split_statements(script):
                cursor.execute(statement)
                _fetch_all_if_rows(cursor)
            cursor.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES (%s)",
                (filename,),
            )
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise

        newly_applied.append(filename)
        log(f"  applied: {filename}")

    return newly_applied


def migration_status(connection, migrations_dir):
    """Return ``[(filename, applied_bool), ...]`` without changing anything."""
    cursor = connection.cursor()
    cursor.execute(CREATE_TABLE_SQL)
    _fetch_all_if_rows(cursor)
    connection.commit()
    done = applied_migrations(cursor)
    return [(name, name in done) for name, _ in discover_migrations(migrations_dir)]
