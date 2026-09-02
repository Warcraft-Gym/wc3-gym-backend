# The backend commands. Run them with `uv run just <recipe>`; the dev dependencies install just.
#
# One module per place the backend runs. A recipe exists in a module only if it makes sense there;
# `just <module> --list` shows what a place supports. README.md, "Where the backend runs", has the table.
# Production is EAShibby's box, reached only through Portainer, so it has no module.

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# The Docker stack on this machine: up, down, logs, psql, serve, alembic, seed.
mod local './just/local.just'

# The Terraform staging box, over SSH: deploy, logs, status, alembic, seed.
mod azure './just/azure.just'

# The Vercel project, prod or staging: deploy, logs, status, migrate, seed, list, drop.
mod vercel './just/vercel.just'

alias up := local::up
alias down := local::down
alias restart := local::restart
alias logs := local::logs
alias status := local::status
alias psql := local::psql
alias serve := local::serve

# Run the tests as CI runs them. Takes pytest arguments, for example `just test -k koth`.
test *args:
    uv run pytest {{ args }}

# Check formatting and lint. CI runs this recipe too.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Type-check with ty. CI runs this recipe too, as its own job.
typecheck:
    uv run ty check app tests

# Format the code and apply the lint fixes ruff can make.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Turn a prod /dump zip into a seed directory: no Nightbot token, no test seasons, no derived columns.
clean-dump zip out_dir *seasons:
    uv run python scripts/clean_dump.py "{{ zip }}" "{{ out_dir }}" {{ seasons }}

# Clone the private seed repo into a directory. No access is not an error: the directory stays empty.
_fetch-seed dir:
    #!/usr/bin/env bash
    set -euo pipefail
    if git clone -q --depth 1 git@github.com:Warcraft-Gym/wc3-gym-backend-db-seed.git "{{ dir }}" 2>/dev/null; then
        echo "seed: $(ls "{{ dir }}"/*.csv | wc -l) tables from Warcraft-Gym/wc3-gym-backend-db-seed"
    else
        echo "seed: no access to Warcraft-Gym/wc3-gym-backend-db-seed, the database stays empty" >&2
    fi

# Load a seed directory, then push its logos/<team id>.<ext> through the upload path, so the database
# owns its blobs and a replaced production logo cannot break it. No token: teams keep the default logo.
_load-seed dir url:
    #!/usr/bin/env bash
    set -euo pipefail
    export DB_URL="{{ url }}"
    # the URLs the load is about to drop; deleted last, so a failed upload leaves an orphan, not a broken image
    previous=$(uv run python -c 'from sqlalchemy import text; from app.core.db import Session, init_engine; init_engine(); print(*[u for (u,) in Session().execute(text("SELECT icon_url FROM teams WHERE icon_url IS NOT NULL"))])')
    uv run python scripts/seed_db.py "{{ dir }}" "$DB_URL"
    if [ -z "${BLOB_READ_WRITE_TOKEN:-}" ]; then echo "logos: BLOB_READ_WRITE_TOKEN is not set, teams keep the default logo" >&2; exit 0; fi
    uv run python - "{{ dir }}/logos" $previous <<'PY'
    import sys
    from pathlib import Path
    from app.api.deps import team_service
    from app.core.db import init_engine
    from app.services import blob
    init_engine()
    logos = sorted(Path(sys.argv[1]).glob("*.*")) if Path(sys.argv[1]).is_dir() else []
    for file in logos:
        team_service.update_icon(int(file.stem), file.read_bytes())
    for url in sys.argv[2:]:
        blob.delete_icon(url)
    print(f"logos: {len(logos)} uploaded, {len(sys.argv) - 2} replaced")
    PY
