# The backend on this machine: Postgres and the backend in Docker, or the app from the working tree.
# The database URL is LOCAL_DB_URL in .env (gitignored, copied from .env.example).

# Recipes run from the repository root, one level up from this file.
set working-directory := '..'

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

image := "gnl-backend:local"
container_db_url := "postgresql+psycopg://gym_user:gym_user@gnl-postgres:5432/gym_backend"
db_url := env("LOCAL_DB_URL", "postgresql+psycopg://gym_user:gym_user@localhost:5432/gym_backend")

default:
    @just --list local

# Build the image from the working tree, then start Postgres and the backend in Docker.
up:
    #!/usr/bin/env bash
    set -euo pipefail
    docker network inspect gnl-net >/dev/null 2>&1 || docker network create gnl-net
    if ! docker ps -a --format '{{{{.Names}}' | grep -qx gnl-postgres; then
        docker run -d --name gnl-postgres --network gnl-net -p 5432:5432 \
            -e POSTGRES_DB=gym_backend -e POSTGRES_USER=gym_user -e POSTGRES_PASSWORD=gym_user \
            -v gnl-postgres-data:/var/lib/postgresql/data postgres:17
    else
        docker start gnl-postgres >/dev/null
    fi
    docker build -t {{ image }} .
    docker rm -f gnl-backend >/dev/null 2>&1 || true
    docker run -d --name gnl-backend --network gnl-net -p 5002:5002 \
        -e DB_URL={{ container_db_url }} \
        -e ADMIN_TOKEN=devtoken -e JWT_SECRET_KEY=devsecret -e JWT_ALGORITHM=HS256 \
        -e TOKEN_TIME=60 \
        -e BOT_CLIENT_TOKEN=dummy -e BOT_WEBHOOK_URL=http://localhost:5002/nowhere \
        -e FRONTEND_URL=http://localhost:5003 \
        {{ image }}
    echo "Waiting for the backend..."
    for _ in $(seq 1 60); do
        curl -fsS -o /dev/null http://localhost:5002/health 2>/dev/null && { echo "Backend: http://localhost:5002 (token: devtoken)"; exit 0; }
        sleep 2
    done
    echo "The backend did not answer on 5002. Log tail:" >&2
    docker logs --tail 20 gnl-backend >&2
    exit 1

# Start the containers again after a stop. Does not rebuild; `up` does.
restart:
    docker start gnl-postgres gnl-backend

# Stop and remove the two containers. The data stays in the gnl-postgres-data volume.
down:
    docker rm -f gnl-backend gnl-postgres 2>/dev/null || true

# Follow the backend log.
logs:
    docker logs -f --tail 200 gnl-backend

# Show the gnl containers.
status:
    docker ps -a --filter name=gnl-

# Open psql on the database.
psql:
    docker exec -it gnl-postgres psql -U gym_user -d gym_backend

# Run the app as Vercel runs it: api/index.py from the working tree, no image, no migration at start.
serve:
    DB_URL="{{ db_url }}" uv run uvicorn api.index:app --reload --port 5002

# Import the S18 and S17 workbooks from tests/data into the running backend, S18 first.
import-xlsx api="http://localhost:5002" token="devtoken":
    #!/usr/bin/env bash
    set -euo pipefail
    access=$(curl -fsS -X POST "{{ api }}/login" -H 'Content-Type: application/json' -d '{"token": "{{ token }}"}' \
        | uv run python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
    for f in tests/data/GNL_S18_export_v2.xlsx tests/data/GNL_S17_export_v2.xlsx; do
        curl -fsS -X POST "{{ api }}/import?create_new=true" -H "Authorization: Bearer $access" -F "file=@$f"; echo
    done

# Bring the database to the latest migration.
migrate:
    DB_URL="{{ db_url }}" uv run alembic upgrade head

# Run any alembic command against the database, for example `just local alembic current`.
alembic *args:
    DB_URL="{{ db_url }}" uv run alembic {{ args }}

# Write a migration for the current models. Read it before committing: autogenerate also drops.
revision message:
    DB_URL="{{ db_url }}" uv run alembic revision --autogenerate -m "{{ message }}"

# Drop every table, then build the schema again. Deletes all data.
reset:
    DB_URL="{{ db_url }}" uv run alembic downgrade base
    DB_URL="{{ db_url }}" uv run alembic upgrade head

# Migrate, then load the private seed repo.
seed:
    #!/usr/bin/env bash
    set -euo pipefail
    seed=$(mktemp -d)
    trap 'rm -rf "$seed"' EXIT
    just _fetch-seed "$seed"
    DB_URL="{{ db_url }}" uv run alembic upgrade head
    if [ -f "$seed/users.csv" ]; then uv run python scripts/seed_db.py "$seed" "{{ db_url }}"; fi
