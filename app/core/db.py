"""One engine and one session factory for the whole process.

The engine and the factory are safe to share between threads. A Session is
not, so every caller opens its own and drops it at the end of the call.

Importing this module opens no connection, and neither does building the
application: the schema is the job of `alembic upgrade head`, so the
application needs no rights to change the database structure and every
worker can start at the same time.
"""

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

# Unbound until init_engine runs; the services import this name at import time
Session = sessionmaker()


def init_engine(db_url: str | None = None) -> Engine:
    """Build the engine and bind the session factory to it.

    Reads DB_URL when the caller passes no url. The two pool settings replace
    a connection the server or a connection pooler dropped while it sat idle.
    """
    db_url = db_url or os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set. See the variable table in README.md.")

    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)
    Session.configure(bind=engine)
    return engine
