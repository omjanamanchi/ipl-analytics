"""
Database access helpers. RULES (see CLAUDE.md):
  * Every value goes in as a parameter (%s / %(name)s). Never build SQL with f-strings
    or + from user input. This is the app's SQL-injection protection.
  * Writes happen inside `transaction(...)` with an explicit isolation level.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None

ISOLATION = {
    "READ COMMITTED": psycopg.IsolationLevel.READ_COMMITTED,
    "REPEATABLE READ": psycopg.IsolationLevel.REPEATABLE_READ,
    "SERIALIZABLE": psycopg.IsolationLevel.SERIALIZABLE,
}


def init_pool(conninfo: str, min_size: int = 1, max_size: int = 5) -> None:
    global _pool
    _pool = ConnectionPool(
        conninfo, min_size=min_size, max_size=max_size, open=True,
        kwargs={"row_factory": dict_row},
    )
    atexit.register(_pool.close)  # close connections cleanly when the process exits


def pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("init_pool() has not been called")
    return _pool


def query(sql: str, params: dict | tuple | None = None) -> list[dict[str, Any]]:
    """Run a read-only query in its own short transaction and return rows as dicts."""
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def query_one(sql: str, params: dict | tuple | None = None) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


@contextmanager
def transaction(isolation: str = "READ COMMITTED", read_only: bool = False) -> Iterator[psycopg.Connection]:
    """Run several statements atomically at the chosen isolation level.

        with transaction("REPEATABLE READ", read_only=True) as conn:
            rows = conn.execute(sql, params).fetchall()

    Commits when the block ends, rolls back if it raises.
    """
    with pool().connection() as conn:
        conn.isolation_level = ISOLATION[isolation]
        conn.read_only = read_only
        try:
            with conn.transaction():
                yield conn
        finally:
            conn.isolation_level = None
            conn.read_only = None
