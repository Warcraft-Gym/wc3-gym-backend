"""Keep the staging Supabase project in step with main.

  migrate          bring wc3gym_template (unlocked for the duration) and wc3gym_staging to head
  drop <branch>    drop the branch's copy, if it has one

DB_URL names the staging project; the database part of it is ignored.
"""

import os
import sys

import psycopg
from alembic import command
from alembic.config import Config

from api.preview_db import SHARED, TEMPLATE, branch_db_name, with_database

base_url = os.environ["DB_URL"]
admin_url = with_database(base_url, "postgres").replace("+psycopg", "")


def upgrade(name: str) -> None:
    os.environ["DB_URL"] = with_database(base_url, name)
    command.upgrade(Config("alembic.ini"), "head")
    print(f"{name} at head")


def migrate() -> None:
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"ALTER DATABASE {TEMPLATE} WITH ALLOW_CONNECTIONS true")
        try:
            upgrade(TEMPLATE)
        finally:
            conn.execute(f"ALTER DATABASE {TEMPLATE} WITH ALLOW_CONNECTIONS false")
            # The pooler keeps a session on any database it has served, and a template must have none
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE datname = %s AND pid <> pg_backend_pid()",
                (TEMPLATE,),
            )
    upgrade(SHARED)


def drop(branch: str) -> None:
    name = branch_db_name(branch)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        if conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone():
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            print(f"dropped {name}")
        else:
            print(f"{name} does not exist, nothing to drop")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["migrate"]:
            migrate()
        case ["drop", branch]:
            drop(branch)
        case _:
            sys.exit(__doc__)
