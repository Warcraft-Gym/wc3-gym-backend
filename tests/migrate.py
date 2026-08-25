"""Run the migrations against a given database.

The suite builds its database the way a deployment does, with
`alembic upgrade head`, so every test run checks that the migrations still
make the schema the code expects.
"""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def upgrade_to(db_url: str, revision: str) -> None:
    # migrations/env.py reads DB_URL, the same variable the application
    # reads, so point it at the database under test.
    previous = os.environ.get("DB_URL")
    os.environ["DB_URL"] = db_url
    try:
        command.upgrade(alembic_config(), revision)
    finally:
        if previous is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = previous


def upgrade_to_head(db_url: str) -> None:
    upgrade_to(db_url, "head")


def fresh_database(directory: Path, name: str) -> str:
    """The url of an empty database.

    A SQLite file in the directory by default. With TEST_DB_URL set, a
    database called `name` on that server instead, dropped and created
    again, so the same suite runs against Postgres.
    """
    server = os.environ.get("TEST_DB_URL")
    if not server:
        return f"sqlite:///{directory / name}.sqlite"

    from sqlalchemy import create_engine, make_url, text

    url = make_url(server)
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()
    return url.set(database=name).render_as_string(hide_password=False)
