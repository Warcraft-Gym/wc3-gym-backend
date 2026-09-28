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
import socket
import struct
from collections.abc import Callable
from concurrent.futures import Executor, Future
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker

# Unbound until init_engine runs; the services import this name at import time
Session = sessionmaker()


@dataclass
class Cost:
    """What one request asked of the database: statements sent, rows returned by reads
    plus rows changed by writes, and the bytes the database connection received."""

    statements: int = 0
    rows: int = 0
    db_bytes: int = 0


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


def submit_in_context[**P, R](
    pool: Executor, fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs
) -> Future[R]:
    """Submit to a thread pool in a copy of the caller's context, so the
    worker's statements count toward the caller's request."""
    context = copy_context()
    return pool.submit(lambda: context.run(fn, *args, **kwargs))


def _count_statement(conn: Any, cursor: Any, *args: Any) -> None:  # noqa: ANN401
    """Add one statement and its rowcount: rows returned by a read, rows changed by a write."""
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


# tcpi_bytes_received in Linux's struct tcp_info, whose fields are only ever appended
TCPI_BYTES_RECEIVED = 128


def received(fd: int) -> int | None:
    """The bytes a TCP socket has received since it opened, as the kernel counts them;
    None where the kernel does not report it."""
    sock = socket.socket(fileno=fd)
    try:
        info = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 256)
    except (AttributeError, OSError):
        return None
    finally:
        sock.detach()  # the socket belongs to the driver: never close it here
    if len(info) < TCPI_BYTES_RECEIVED + 8:
        return None
    return struct.unpack_from("Q", info, TCPI_BYTES_RECEIVED)[0]


def _start_received(dbapi_conn: Any, record: Any) -> None:  # noqa: ANN401
    record.info["received"] = 0


def _count_received(dbapi_conn: Any, record: Any) -> None:  # noqa: ANN401
    """On check-in, add what the connection received since its last check-in to the
    request's tally: the connect handshake, the ping, every result and the commit.
    An invalidated connection comes back without a driver connection or with a closed one;
    what it received since its last check-in is not counted."""
    if dbapi_conn is None or dbapi_conn.closed:
        return
    now = received(dbapi_conn.pgconn.socket)
    if now is None:
        return
    cost = _cost.get()
    if cost is not None:
        cost.db_bytes += now - record.info.get("received", 0)
    record.info["received"] = now


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
    if engine.dialect.name == "postgresql":
        event.listen(engine.pool, "connect", _start_received)
        event.listen(engine.pool, "checkin", _count_received)
    Session.configure(bind=engine)
    # the listeners: the blob store follows the rows, and every fixture and
    # series names the round it is played in
    from app.services import blob, round_link  # noqa: F401

    return engine
