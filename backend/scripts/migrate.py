"""Apply pending database migrations.

Run from the ``backend/`` directory:

    python scripts/migrate.py            # apply all pending migrations
    python scripts/migrate.py --status   # show applied / pending, change nothing

Connection settings come from ``backend/.env`` (same as the app).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
_REPO = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)

MIGRATIONS_DIR = os.path.join(_REPO, "database", "migrations")

from database import get_db_connection  # noqa: E402
from migrations_runner import run_migrations, migration_status  # noqa: E402


def main(argv):
    connection = get_db_connection()
    if connection is None:
        print("ERROR: could not connect to the database. Check backend/.env")
        return 1
    try:
        if "--status" in argv:
            print(f"Migrations directory: {MIGRATIONS_DIR}")
            for filename, applied in migration_status(connection, MIGRATIONS_DIR):
                mark = "x" if applied else " "
                print(f"  [{mark}] {filename}")
            return 0

        applied = run_migrations(connection, MIGRATIONS_DIR)
        if applied:
            print(f"Applied {len(applied)} migration(s):")
            for name in applied:
                print(f"  - {name}")
        else:
            print("Database is up to date; no migrations to apply.")
        return 0
    finally:
        try:
            connection.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
