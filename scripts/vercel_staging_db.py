"""The staging Supabase project behind Vercel previews. DB_URL names the project.

migrate               bring wc3gym_template (unlocked for the duration) and wc3gym_staging to head
seed <seed_dir>       reseed the template from a clean-dump directory, then recreate wc3gym_staging from it
list                  the databases on the project
drop <database>       drop one branch copy by name; the template and the shared database are refused
drop-branch <branch>  drop the copy a branch owns, if any (the workflow calls this on branch delete)
"""

import os
import subprocess
import sys

import psycopg
from alembic import command
from alembic.config import Config

from api.preview_db import SHARED, TEMPLATE, branch_db_name, with_database

base_url = os.environ["DB_URL"]
admin_url = with_database(base_url, "postgres").replace("+psycopg", "")


def admin() -> psycopg.Connection:
    return psycopg.connect(
        admin_url, autocommit=True
    )  # CREATE/DROP/ALTER DATABASE cannot run in a transaction


def upgrade(name: str) -> None:
    os.environ["DB_URL"] = with_database(base_url, name)
    command.upgrade(Config("alembic.ini"), "head")
    print(f"{name} at head")


def unlock_template(conn: psycopg.Connection) -> None:
    conn.execute(f"ALTER DATABASE {TEMPLATE} WITH ALLOW_CONNECTIONS true")


def lock_template(conn: psycopg.Connection) -> None:
    conn.execute(f"ALTER DATABASE {TEMPLATE} WITH ALLOW_CONNECTIONS false")
    # The pooler keeps a session on any database it has served, and a template must have none
    conn.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
        (TEMPLATE,),
    )


def migrate() -> None:
    with admin() as conn:
        unlock_template(conn)
        try:
            upgrade(TEMPLATE)
        finally:
            lock_template(conn)
    upgrade(SHARED)


def seed(seed_dir: str) -> None:
    with admin() as conn:
        if not conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEMPLATE,)
        ).fetchone():
            conn.execute(f"CREATE DATABASE {TEMPLATE}")
        unlock_template(conn)
        try:
            upgrade(TEMPLATE)
            subprocess.run(
                [
                    sys.executable,
                    "scripts/seed_db.py",
                    seed_dir,
                    with_database(base_url, TEMPLATE),
                ],
                check=True,
            )
        finally:
            lock_template(conn)
        conn.execute(f"DROP DATABASE IF EXISTS {SHARED} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {SHARED} TEMPLATE {TEMPLATE}")
        print(f"{SHARED} recreated from {TEMPLATE}")


def list_databases() -> None:
    with admin() as conn:
        for name, allow in conn.execute(
            "SELECT datname, datallowconn FROM pg_database WHERE datname LIKE 'wc3gym_%' ORDER BY 1"
        ):
            print(name, "" if allow else "(locked template)")


def drop(name: str) -> None:
    if name in (TEMPLATE, SHARED) or not name.startswith("wc3gym_"):
        sys.exit(
            f"refusing to drop {name}: only branch copies (wc3gym_<branch>_<hash>) can be dropped"
        )
    with admin() as conn:
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
        case ["seed", seed_dir]:
            seed(seed_dir)
        case ["list"]:
            list_databases()
        case ["drop", name]:
            drop(name)
        case ["drop-branch", branch]:
            drop(branch_db_name(branch))
        case _:
            sys.exit(__doc__)
