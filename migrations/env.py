"""Alembic environment.

The url comes from DB_URL, the variable the application reads, so a
migration always runs against the database the application would open.

Importing app.models registers every table on SQLModel.metadata, which is
what autogenerate compares the live database against.
"""

import importlib
import os
import pkgutil
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

import app.models

load_dotenv()

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers stays off: the test suite runs a migration
    # inside a process that has already configured logging.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

for module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{module.name}")

target_metadata = SQLModel.metadata


def get_url():
    url = os.getenv("DB_URL")
    if not url:
        raise RuntimeError("DB_URL is not set. See the variable table in README.md.")
    return url


def run_migrations_offline():
    """Emit the SQL of a migration without connecting."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run the migrations against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
