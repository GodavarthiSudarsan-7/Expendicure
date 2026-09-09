import mysql.connector
from mysql.connector import Error, IntegrityError, pooling
from config import Config

# Re-exported so route modules can catch a single, stable exception type
# without importing mysql.connector directly.
__all__ = [
    "DatabaseError",
    "IntegrityError",
    "get_db_connection",
    "execute_query",
    "run_transaction",
]


class DatabaseError(Exception):
    """Raised when a database operation cannot be completed.

    Used by callers that opt in via ``raise_on_error=True`` (or by
    ``run_transaction``) so they can distinguish a real failure from an
    empty result set."""


def _connection_kwargs():
    return dict(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        port=Config.MYSQL_PORT,
    )


# Lazily-created pool. If the pool cannot be built (e.g. MySQL not reachable at
# import time) we fall back to plain per-call connections so behaviour matches
# the original implementation.
_pool = None
_pool_disabled = False


def _get_pool():
    global _pool, _pool_disabled
    if _pool is not None or _pool_disabled:
        return _pool
    try:
        _pool = pooling.MySQLConnectionPool(
            pool_name="expendicure_pool",
            pool_size=5,
            pool_reset_session=True,
            **_connection_kwargs(),
        )
    except Error as e:
        print(f"Connection pool unavailable, using direct connections: {e}")
        _pool_disabled = True
    return _pool


def _raw_connection():
    pool = _get_pool()
    if pool is not None:
        try:
            return pool.get_connection()
        except Error as e:
            print(f"Pool get_connection failed, using direct connection: {e}")
    try:
        return mysql.connector.connect(**_connection_kwargs())
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None


def get_db_connection():
    """Backwards-compatible helper: returns a live connection or None."""
    return _raw_connection()


def execute_query(query, params=None, fetch_one=False, fetch_all=False,
                  commit=False, raise_on_error=False):
    """Run a single statement.

    Default behaviour is unchanged: returns the row(s) / lastrowid, or ``None``
    on any failure. Pass ``raise_on_error=True`` to get a ``DatabaseError`` (or
    the underlying mysql ``Error``) instead of a silent ``None`` — this lets new
    code tell "query failed" apart from "no rows".
    """
    connection = _raw_connection()
    if not connection:
        if raise_on_error:
            raise DatabaseError("Could not connect to database")
        return None
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(query, params or ())
        if commit:
            connection.commit()
            return cursor.lastrowid
        if fetch_one:
            return cursor.fetchone()
        if fetch_all:
            return cursor.fetchall()
        return None
    except Error as e:
        print(f"Database error: {e}")
        if raise_on_error:
            raise
        return None
    finally:
        cursor.close()
        connection.close()


def run_transaction(fn):
    """Run ``fn(cursor)`` inside one transaction on a single connection.

    Commits if ``fn`` returns normally, rolls back and re-raises if it throws.
    Returns whatever ``fn`` returns. Raises ``DatabaseError`` if no connection
    is available.
    """
    connection = _raw_connection()
    if not connection:
        raise DatabaseError("Could not connect to database")
    cursor = connection.cursor(dictionary=True)
    try:
        result = fn(cursor)
        connection.commit()
        return result
    except Exception:
        try:
            connection.rollback()
        except Error:
            pass
        raise
    finally:
        cursor.close()
        connection.close()
