# Database recipes. Every one takes a deployment path and an environment:
#   just db <recipe> local
#   just db <recipe> vercel prod
#   just db <recipe> vercel staging
# The URL comes from .env (LOCAL_DB_URL, VERCEL_PROD_DB_URL, VERCEL_STAGING_DB_URL); scripts/db_target.py
# answers "not implemented" for the Azure box, which is seeded over SSH from the gym root.

seed_repo := "Warcraft-Gym/wc3-gym-backend-db-seed"

# Bring the database to the latest migration. For vercel staging: the template and the shared database.
migrate path env="":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(uv run python scripts/db_target.py {{ path }} {{ env }})
    if [ "{{ path }} {{ env }}" = "vercel staging" ]; then
        DB_URL="$url" uv run python scripts/vercel_staging_db.py migrate
    else
        DB_URL="$url" uv run alembic upgrade head
    fi

# Show the revision the database is on, and the revisions that exist.
status path env="":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(uv run python scripts/db_target.py {{ path }} {{ env }})
    DB_URL="$url" uv run alembic current
    DB_URL="$url" uv run alembic history

# Write a migration for the current models against the local database. Read it before committing: autogenerate also drops.
revision message:
    DB_URL="$(uv run python scripts/db_target.py local)" uv run alembic revision --autogenerate -m "{{ message }}"

# Drop every table of the local database, then build the schema again. Deletes all data.
reset:
    DB_URL="$(uv run python scripts/db_target.py local)" uv run alembic downgrade base
    DB_URL="$(uv run python scripts/db_target.py local)" uv run alembic upgrade head

# Migrate, then load the private seed repo. No access to it is not an error: the database stays migrated and empty.
seed path env="":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(uv run python scripts/db_target.py {{ path }} {{ env }})
    seed=$(mktemp -d)
    if gh repo clone {{ seed_repo }} "$seed" -- -q --depth 1 2>/dev/null; then
        echo "seed: $(ls "$seed"/*.csv | wc -l) tables from {{ seed_repo }}"
    else
        echo "seed: no access to {{ seed_repo }}, the database stays empty" >&2
    fi
    if [ "{{ path }} {{ env }}" = "vercel staging" ]; then
        [ -f "$seed/users.csv" ] && DB_URL="$url" uv run python scripts/vercel_staging_db.py seed "$seed" \
            || DB_URL="$url" uv run python scripts/vercel_staging_db.py migrate
    else
        DB_URL="$url" uv run alembic upgrade head
        [ -f "$seed/users.csv" ] && uv run python scripts/seed_db.py "$seed" "$url"
    fi
    rm -rf "$seed"

# List the databases of the vercel staging project: the template, the shared database and the branch copies.
list path env="":
    #!/usr/bin/env bash
    set -euo pipefail
    [ "{{ path }} {{ env }}" = "vercel staging" ] || { echo "not implemented: only the vercel staging project holds more than one database" >&2; exit 2; }
    DB_URL="$(uv run python scripts/db_target.py vercel staging)" uv run python scripts/vercel_staging_db.py list

# Drop one branch copy on the vercel staging project. The template, the shared database and every other target are refused.
drop path env database:
    #!/usr/bin/env bash
    set -euo pipefail
    [ "{{ path }} {{ env }}" = "vercel staging" ] || { echo "not implemented: nothing is dropped anywhere but the vercel staging project" >&2; exit 2; }
    DB_URL="$(uv run python scripts/db_target.py vercel staging)" uv run python scripts/vercel_staging_db.py drop "{{ database }}"

# Turn a prod /dump zip into a seed directory: no Nightbot token, no test seasons, no derived columns.
clean-dump zip out_dir *seasons:
    uv run python scripts/clean_dump.py "{{ zip }}" "{{ out_dir }}" {{ seasons }}
