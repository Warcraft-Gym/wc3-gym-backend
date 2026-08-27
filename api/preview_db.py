"""One database per Vercel preview, copied from the seeded wc3gym_base template on the staging project.

The preview DB_URL names the project; the pull request number picks the database. Run as a script
in the preview build to create the copy and migrate it; imported by api/index.py to point the app at it.
"""

import os
import re
from urllib.parse import urlsplit, urlunsplit


def preview_db_name() -> str | None:
    """wc3gym_pr<N> for a pull request preview, wc3gym_<branch> for a plain branch push, None outside previews."""
    if os.environ.get("VERCEL_ENV") != "preview":
        return None
    pr = os.environ.get("VERCEL_GIT_PULL_REQUEST_ID")
    if pr:
        return f"wc3gym_pr{pr}"
    ref = re.sub(
        r"[^a-z0-9]+", "_", os.environ.get("VERCEL_GIT_COMMIT_REF", "").lower()
    )
    return f"wc3gym_{ref[:40]}" if ref else None


def with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


def main() -> None:
    import psycopg
    from alembic import command
    from alembic.config import Config

    name = preview_db_name()
    if not name:
        return
    base_url = os.environ["DB_URL"]
    # CREATE DATABASE cannot run inside a transaction, hence autocommit
    with psycopg.connect(
        with_database(base_url, "postgres").replace("+psycopg", ""), autocommit=True
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}" TEMPLATE wc3gym_base')
            print(f"created {name} from wc3gym_base")
    os.environ["DB_URL"] = with_database(base_url, name)
    command.upgrade(Config("alembic.ini"), "head")


if __name__ == "__main__":
    main()
