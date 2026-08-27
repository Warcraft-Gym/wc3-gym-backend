"""Which database a Vercel preview uses on the staging Supabase project.

Every preview uses the shared wc3gym_staging database. A branch that adds a migration gets its own
copy of the locked wc3gym_template instead, named after the branch, migrated in the preview build.
Run as a script in the preview build to make that choice and create the copy; imported by
api/index.py to point the app at the right database at cold start.
"""

import hashlib
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SHARED = "wc3gym_staging"
TEMPLATE = "wc3gym_template"


def branch_db_name(branch: str) -> str:
    """wc3gym_<slug>_<hash>: the slug (lower-case, non-alphanumerics folded to _, at most 16 chars) is
    for reading, the 8-hex sha1 of the exact branch name keeps two branches from sharing a database
    when their slugs collide. 32 chars at most, within Postgres's 63-byte identifier limit."""
    slug = re.sub(r"[^a-z0-9]+", "_", branch.lower()).strip("_")[:16].rstrip("_")
    return f"wc3gym_{slug}_{hashlib.sha1(branch.encode()).hexdigest()[:8]}"


def migrations_fingerprint(versions: Path = Path("migrations/versions")) -> str:
    """sha1 over the branch's migration files: it changes when one is edited, renamed or removed."""
    digest = hashlib.sha1()
    for path in sorted(versions.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


def preview_branch() -> str | None:
    if os.environ.get("VERCEL_ENV") != "preview":
        return None
    return os.environ.get("VERCEL_GIT_COMMIT_REF") or None


def runtime_database() -> str | None:
    """The database this preview serves from: the branch copy if the build made one, else the shared one."""
    branch = preview_branch()
    if not branch:
        return None
    import psycopg

    name = branch_db_name(branch)
    with psycopg.connect(
        with_database(os.environ["DB_URL"], "postgres").replace("+psycopg", "")
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
    return name if exists else SHARED


def main() -> None:
    import psycopg
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    branch = preview_branch()
    if not branch:
        return
    base_url = os.environ["DB_URL"]
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = scripts.get_heads()
    if len(heads) != 1:
        sys.exit(f"this branch has {len(heads)} migration heads, merge them into one")
    branch_head = heads[0]
    with psycopg.connect(
        with_database(base_url, SHARED).replace("+psycopg", "")
    ) as conn:
        shared_rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()[
            0
        ]
    if shared_rev == branch_head:
        print(f"no new migration, the preview uses {SHARED}")
        return
    if shared_rev not in {r.revision for r in scripts.walk_revisions()}:
        sys.exit(
            f"{SHARED} is at {shared_rev}, which this branch does not know: rebase onto main"
        )

    name = branch_db_name(branch)
    fingerprint = migrations_fingerprint()
    # CREATE DATABASE cannot run inside a transaction, hence autocommit
    with psycopg.connect(
        with_database(base_url, "postgres").replace("+psycopg", ""), autocommit=True
    ) as conn:
        comment = conn.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (name,),
        ).fetchone()
        if comment and comment[0] != fingerprint:
            # a copy built from other migration files, or one whose build died before commenting
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            print(f"dropped {name}, it does not match this branch's migrations")
            comment = None
        if not comment:
            conn.execute(f'CREATE DATABASE "{name}" TEMPLATE {TEMPLATE}')
            print(f"created {name} from {TEMPLATE}")
        os.environ["DB_URL"] = with_database(base_url, name)
        command.upgrade(Config("alembic.ini"), "head")
        conn.execute(f"COMMENT ON DATABASE \"{name}\" IS '{fingerprint}'")
    print(f"the preview uses {name} at {branch_head}")


if __name__ == "__main__":
    main()
