"""Adapter that wires the pure ``finance`` layer to the real database.

This module is allowed to import ``database``; the ``finance`` package is not.
Routes call :func:`get_repository` to obtain a
:class:`finance.repository.FinanceRepository` backed by ``execute_query``.
"""

from database import execute_query
from finance.repository import FinanceRepository


def _query(sql, params=(), one=False):
    return execute_query(
        sql,
        tuple(params),
        fetch_one=one,
        fetch_all=not one,
    )


def get_repository():
    return FinanceRepository(_query)
