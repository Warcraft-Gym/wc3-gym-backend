"""One engine and one session factory for the whole process.

The engine and the factory are safe to share between threads. A Session is
not, so every caller opens its own with `Session.begin()`: one transaction per
call, commit on success, roll back on error, always close. Callers must not
commit; to share a transaction, pass the session instead of opening a new one.

Importing this module opens no connection, and neither does building the
application: the schema is the job of `alembic upgrade head`, so the
application needs no rights to change the database structure and every
worker can start at the same time.
"""

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker

# Unbound until init_engine runs; the services import this name at import time
Session = sessionmaker()


@dataclass
class Cost:
    """What one request asked of the database: statements sent and rows back."""

    statements: int = 0
    rows: int = 0


# Mutable, so a worker thread that copied the request context adds to the same tally
_cost: ContextVar[Cost | None] = ContextVar("request_cost", default=None)


def start_request_cost() -> Cost:
    """Start a fresh tally for the current request and return it."""
    cost = Cost()
    _cost.set(cost)
    return cost


def request_cost() -> Cost | None:
    """The tally of the current request; None outside a request."""
    return _cost.get()


def _count_statement(conn: Any, cursor: Any, *args: Any) -> None:  # noqa: ANN401
    """Add one statement and the rows the driver reports to the request tally."""
    cost = _cost.get()
    if cost is not None:
        cost.statements += 1
        cost.rows += max(cursor.rowcount, 0)


def _count_row(cursor: Any, row: tuple[Any, ...]) -> tuple[Any, ...]:  # noqa: ANN401
    """SQLite reports no rowcount for a SELECT, so it counts each row it fetches."""
    cost = _cost.get()
    if cost is not None:
        cost.rows += 1
    return row


def rel(attr: Any) -> InstrumentedAttribute[Any]:  # noqa: ANN401
    """The relationship twin of sqlmodel.col(): the loader options want the
    instrumented attribute, and SQLModel types the class attribute as its value."""
    return attr


def init_engine(db_url: str | None = None) -> Engine:
    """Build the engine and bind the session factory to it.

    Reads DB_URL when the caller passes no url. The two pool settings replace
    a connection the server or a connection pooler dropped while it sat idle.
    """
    db_url = db_url or os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set. See the variable table in README.md.")

    # no server-side prepared statements: the Supabase transaction pooler rejects them
    connect_args = (
        {"prepare_threshold": None} if db_url.startswith("postgresql") else {}
    )
    engine = create_engine(
        db_url, pool_pre_ping=True, pool_recycle=3600, connect_args=connect_args
    )
    if engine.dialect.name == "sqlite":
        # the tests run on SQLite, which enforces foreign keys and their cascades only when asked
        event.listen(
            engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
        )
        event.listen(
            engine, "connect", lambda conn, _: setattr(conn, "row_factory", _count_row)
        )
    event.listen(engine, "after_cursor_execute", _count_statement)
    Session.configure(bind=engine)
    # the listeners: the blob store follows the rows, and every fixture and
    # series names the round it is played in
    from app.services import blob, round_link  # noqa: F401

    return engine
