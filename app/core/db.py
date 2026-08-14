"""One engine and one session factory for the whole process.

The engine and the factory are safe to share between threads. A Session is
not, so every caller opens its own and drops it at the end of the call.

Importing this module opens no connection. The application factory in
app/main.py calls init_engine, which builds the engine and binds the
factory below to it.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

# Unbound until init_engine runs. The database services import this name at
# import time, so the object has to exist before the engine does.
Session = sessionmaker()


def init_engine(db_url=None):
    """Build the engine and bind the session factory to it.

    Reads DB_URL when the caller passes no url. Both engine settings are for
    MySQL, which drops a connection that stays idle.
    """
    db_url = db_url or os.getenv("DB_URL")
    if not db_url:
        raise RuntimeError("DB_URL is not set. See the variable table in README.md.")

    engine = create_engine(db_url, pool_pre_ping=True, pool_recycle=3600)
    Session.configure(bind=engine)
    return engine


def init_schema(engine):
    """Create the tables that do not exist yet. Runs one time at start up.

    create_all asks whether a table exists and then creates it, so workers
    that start against an empty database race, and one stops with "table
    already exists". Run gunicorn with --preload to use more than one
    worker: the parent then builds the application one time, and the dispose
    below leaves each worker an empty pool, which a forked process needs.
    """
    SQLModel.metadata.create_all(engine)

    # Start up is the only user of this connection. Giving it back also
    # leaves nothing for a forked worker to inherit.
    engine.dispose()
