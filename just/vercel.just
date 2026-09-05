# The Vercel project. Every recipe takes an environment, prod by default: `just vercel migrate staging`.
# prod is the production deployment and its Supabase project; staging is the preview project, which holds
# the locked template, the shared database and one copy per branch that adds a migration (docs/PREVIEW-DATABASES.md).
# The URLs are VERCEL_PROD_DB_URL and VERCEL_STAGING_DB_URL in .env (gitignored). A push to main deploys prod on its own.

# Recipes run from the repository root, one level up from this file.
set working-directory := '..'

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

default:
    @just --list vercel

# Print the database URL of an environment.
url env="prod":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{ env }}" in
    (prod)    echo "${VERCEL_PROD_DB_URL:?VERCEL_PROD_DB_URL is not set in .env}" ;;
    (staging) echo "${VERCEL_STAGING_DB_URL:?VERCEL_STAGING_DB_URL is not set in .env}" ;;
    (*)       echo "env must be prod or staging" >&2; exit 2 ;;
    esac

# Deploy the working tree: prod promotes it, staging makes a preview.
deploy env="prod":
    npx vercel deploy {{ if env == "prod" { "--prod" } else { "" } }}

# Follow the production log. A preview has no fixed URL: `npx vercel logs <preview url>`.
logs:
    npx vercel logs --prod

# List the deployments.
status env="prod":
    npx vercel ls {{ if env == "prod" { "--prod" } else { "" } }}

# Bring the database to the latest migration. For staging: the template and the shared database.
migrate env="prod":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(just vercel url {{ env }})
    if [ "{{ env }}" = staging ]; then
        DB_URL="$url" uv run python -m api.preview_db migrate
    else
        DB_URL="$url" uv run alembic upgrade head
    fi

# Run any alembic command against the database. The environment is required: `just vercel alembic prod current`.
alembic env *args:
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(just vercel url {{ env }})
    DB_URL="$url" uv run alembic {{ args }}

# Migrate, then load the private seed repo. For staging: the template, then the shared database from it.
seed env="prod":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(just vercel url {{ env }})
    seed=$(mktemp -d)
    trap 'rm -rf "$seed"' EXIT
    just _fetch-seed "$seed"
    if [ "{{ env }}" = staging ]; then
        if [ -f "$seed/users.csv" ]; then
            DB_URL="$url" uv run python -m api.preview_db seed "$seed"
        else
            DB_URL="$url" uv run python -m api.preview_db migrate
        fi
    else
        DB_URL="$url" uv run alembic upgrade head
        if [ -f "$seed/users.csv" ]; then just _load-seed "$seed" "$url"; fi
    fi

# Import the W3C map pool: create, rename and picture every ladder map, no season pool change. For staging: the shared database.
import-maps env="prod":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(just vercel url {{ env }})
    if [ "{{ env }}" = staging ]; then
        url=$(DB_URL="$url" uv run python -c 'import os; from api.preview_db import SHARED, with_database; print(with_database(os.environ["DB_URL"], SHARED))')
    fi
    DB_URL="$url" uv run python -c 'from app.api.deps import map_service; from app.core.db import init_engine; init_engine(); print(len(map_service.import_ladder_maps([row.w3c_name for row in map_service.ladder_import_preview()])), "maps imported")'

# Build the review season on the shared staging database: you (the first ADMIN_DISCORD_IDS entry) against
# the reviewer's Discord id: `just vercel review-season staging <reviewer discord id>`.
review-season env reviewer me="":
    #!/usr/bin/env bash
    set -euo pipefail
    url=$(just vercel url {{ env }})
    if [ "{{ env }}" = staging ]; then
        url=$(DB_URL="$url" uv run python -c 'import os; from api.preview_db import SHARED, with_database; print(with_database(os.environ["DB_URL"], SHARED))')
    fi
    me="{{ me }}"
    DB_URL="$url" uv run python scripts/review_season.py "${me:-${ADMIN_DISCORD_IDS%%,*}}" "{{ reviewer }}"

# List the staging databases: the template, the shared database and the branch copies.
list:
    DB_URL="$(just vercel url staging)" uv run python -m api.preview_db list

# Drop one branch copy on staging. The template and the shared database are refused.
drop database:
    DB_URL="$(just vercel url staging)" uv run python -m api.preview_db drop "{{ database }}"
