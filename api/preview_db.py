"""Which database a Vercel preview uses on the staging Supabase project, and the admin steps on it.

Every preview uses the shared wc3gym_staging database. A branch that adds a migration gets its own
copy of the locked wc3gym_template instead, named after the branch, migrated in the preview build.
Imported by api/index.py to point the app at the right database at cold start. DB_URL names the project.

python -m api.preview_db                       the preview build: choose or create the branch copy (vercel.json)
python -m api.preview_db migrate               bring wc3gym_template (unlocked for the duration) and wc3gym_staging to head
python -m api.preview_db seed <seed_dir>       reseed the template from a seed directory, then recreate wc3gym_staging from it
python -m api.preview_db list                  the databases on the project
python -m api.preview_db drop <database>       drop one branch copy by name; the template and the shared database are refused
python -m api.preview_db drop-branch <branch>  drop the copy a branch owns, if any (the workflow calls this on branch delete)
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

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


def connect(name: str, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(
        with_database(os.environ["DB_URL"], name).replace("+psycopg", ""),
        autocommit=autocommit,
    )


def admin() -> psycopg.Connection:
    # CREATE/DROP/ALTER DATABASE cannot run in a transaction
    return connect("postgres", autocommit=True)


def exists(conn: psycopg.Connection, name: str) -> bool:
    return bool(
        conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    )


def preview_branch() -> str | None:
    if os.environ.get("VERCEL_ENV") != "preview":
        return None
    return os.environ.get("VERCEL_GIT_COMMIT_REF") or None


def runtime_database() -> str | None:
    """The database this preview serves from: the branch copy if the build made one, else the shared one."""
    branch = preview_branch()
    if not branch:
        return None
    name = branch_db_name(branch)
    with connect("postgres") as conn:
        return name if exists(conn, name) else SHARED


def upgrade(name: str) -> None:
    from alembic import command
    from alembic.config import Config

    os.environ["DB_URL"] = with_database(os.environ["DB_URL"], name)
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
        if not exists(conn, TEMPLATE):
            conn.execute(f"CREATE DATABASE {TEMPLATE}")
        unlock_template(conn)
        try:
            upgrade(TEMPLATE)
            subprocess.run(
                [
                    "just",
                    "_load-seed",
                    seed_dir,
                    with_database(os.environ["DB_URL"], TEMPLATE),
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
        if exists(conn, name):
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
            print(f"dropped {name}")
        else:
            print(f"{name} does not exist, nothing to drop")


def build() -> None:
    """The preview build: pick the shared database, or create and migrate the branch copy."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    branch = preview_branch()
    if not branch:
        return
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = scripts.get_heads()
    if len(heads) != 1:
        sys.exit(f"this branch has {len(heads)} migration heads, merge them into one")
    branch_head = heads[0]
    with connect(SHARED) as conn:
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
    with admin() as conn:
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
        upgrade(name)
        conn.execute(f"COMMENT ON DATABASE \"{name}\" IS '{fingerprint}'")
    print(f"the preview uses {name} at {branch_head}")


if __name__ == "__main__":
    match sys.argv[1:]:
        case []:
            build()
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
