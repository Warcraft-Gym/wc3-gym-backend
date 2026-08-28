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
        DB_URL="$url" uv run python scripts/vercel_staging_db.py migrate
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
            DB_URL="$url" uv run python scripts/vercel_staging_db.py seed "$seed"
        else
            DB_URL="$url" uv run python scripts/vercel_staging_db.py migrate
        fi
    else
        DB_URL="$url" uv run alembic upgrade head
        if [ -f "$seed/users.csv" ]; then uv run python scripts/seed_db.py "$seed" "$url"; fi
    fi

# List the staging databases: the template, the shared database and the branch copies.
list:
    DB_URL="$(just vercel url staging)" uv run python scripts/vercel_staging_db.py list

# Drop one branch copy on staging. The template and the shared database are refused.
drop database:
    DB_URL="$(just vercel url staging)" uv run python scripts/vercel_staging_db.py drop "{{ database }}"
