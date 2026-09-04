"""Alembic environment.

The url comes from DB_URL, the variable the application reads, so a
migration always runs against the database the application would open.

Importing app.models registers every table on SQLModel.metadata, which is
what autogenerate compares the live database against.

Each revision commits on its own, so a revision that adds an enum value can
be followed by one that uses it.
"""

import logging
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import app.models  # noqa: F401  # the import is the registration

load_dotenv()

config = context.config

logging.basicConfig(level=logging.INFO)

target_metadata = SQLModel.metadata


def get_url() -> str:
    url = os.getenv("DB_URL")
    if not url:
        raise RuntimeError("DB_URL is not set. See the variable table in README.md.")
    return url


def run_migrations_online() -> None:
    """Run the migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
