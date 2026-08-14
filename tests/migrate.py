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


def alembic_config():
    config = Config(REPO_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def upgrade_to_head(db_url):
    # migrations/env.py reads DB_URL, the same variable the application
    # reads, so point it at the database under test.
    previous = os.environ.get("DB_URL")
    os.environ["DB_URL"] = db_url
    try:
        command.upgrade(alembic_config(), "head")
    finally:
        if previous is None:
            os.environ.pop("DB_URL", None)
        else:
            os.environ["DB_URL"] = previous
