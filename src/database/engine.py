"""One engine and one session factory for the whole process.

The engine and the factory are safe to share between threads. A Session is
not, so every caller opens its own and drops it at the end of the call.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.base import Base

# src/__init__.py loads the .env file before it imports this module.
DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise RuntimeError("DB_URL is not set. See the variable table in README.md.")

# Both settings are for MySQL, which drops a connection that stays idle.
engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600)

Session = sessionmaker(bind=engine)


def init_schema():
    """Create the tables that do not exist yet. Runs one time at start up.

    create_all asks whether a table exists and then creates it, so workers
    that start against an empty database race, and one stops with "table
    already exists". Run gunicorn with --preload to use more than one
    worker: the parent then imports one time, and the dispose below leaves
    each worker an empty pool, which a forked process needs.
    """
    Base.metadata.create_all(engine)

    # Start up is the only user of this connection. Giving it back also
    # leaves nothing for a forked worker to inherit.
    engine.dispose()
