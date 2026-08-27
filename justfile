# Local dev stack: Postgres and the backend, both in Docker.
# just installs with the dev dependencies; run recipes with `uv run just <recipe>`.

set shell := ["bash", "-euo", "pipefail", "-c"]

# The tag `up` builds from the working tree. It is a local development
# image and nothing publishes it, so a deployment names its own image.
image := "gnl-backend:local"

# The same database under its two names. Which one is right depends on
# where the command runs, and that is the usual reason a connection fails.
# The backend container reaches Postgres over the gnl-net network by container
# name; a command on the host reaches it through the published port.
container_db_url := "postgresql+psycopg://gym_user:gym_user@gnl-postgres:5432/gym_backend"
host_db_url := "postgresql+psycopg://gym_user:gym_user@localhost:5432/gym_backend"

default:
    @just --list

# Migrate, seed, list and drop databases by deployment path and environment. `just db` lists them.
mod db

# Start Postgres, then build and start the backend on port 5002.
up:
    #!/usr/bin/env bash
    set -euo pipefail

    docker network inspect gnl-net >/dev/null 2>&1 || docker network create gnl-net

    if docker container inspect gnl-postgres >/dev/null 2>&1; then
        docker start gnl-postgres
    else
        docker run -d --name gnl-postgres --network gnl-net \
            -e POSTGRES_DB=gym_backend \
            -e POSTGRES_USER=gym_user \
            -e POSTGRES_PASSWORD=gym_user \
            -p 5432:5432 \
            -v gnl-postgres-data:/var/lib/postgresql/data \
            postgres:17
    fi

    echo "Waiting for Postgres..."
    for _ in $(seq 1 30); do
        if docker exec gnl-postgres pg_isready -U gym_user -d gym_backend -q 2>/dev/null; then
            break
        fi
        sleep 2
    done

    docker build -t {{image}} {{justfile_directory()}}
    docker rm -f gnl-backend >/dev/null 2>&1 || true
    docker run -d --name gnl-backend --network gnl-net -p 5002:5002 \
        --log-opt max-size=10m --log-opt max-file=5 \
        -e DB_URL="{{container_db_url}}" \
        -e ADMIN_TOKEN=devtoken \
        -e JWT_SECRET_KEY=devsecret \
        -e JWT_ALGORITHM=HS256 \
        -e TOKEN_TIME=60 \
        -e REFRESH_TOKEN_TIME=1440 \
        -e BOT_CLIENT_TOKEN=dummy \
        -e BOT_WEBHOOK_URL=http://localhost:9999 \
        -e FRONTEND_URL=http://localhost:5003 \
        {{image}}

    # The container runs the migration before uvicorn binds, so one answered
    # route means the schema step also succeeded.
    # /health runs a query, so an answer also proves the database link.
    echo "Waiting for the backend..."
    for try in $(seq 1 45); do
        if curl -fsS -o /dev/null http://localhost:5002/health 2>/dev/null; then
            break
        fi
        if [ "$try" -eq 45 ]; then
            echo "The backend did not answer on 5002. Log tail:" >&2
            docker logs --tail 20 gnl-backend >&2
            exit 1
        fi
        sleep 2
    done

    echo
    echo "Backend: http://localhost:5002/docs (admin token: devtoken)"

# Start the stopped containers again, Postgres first. Use after Docker Desktop restarts.
restart:
    docker start gnl-postgres
    docker start gnl-backend

# Follow the backend log, where the migration and the server both write.
logs *args:
    docker logs --follow --tail 50 {{args}} gnl-backend

# Open psql on the development database.
psql:
    docker exec -it gnl-postgres psql -U gym_user -d gym_backend





# Stop the backend and Postgres, keeping the data. A missing container is not an error.
down:
    docker stop gnl-backend gnl-postgres 2>/dev/null || true

# Run the tests as CI runs them. Takes pytest arguments, for example `just test -k koth`.
test *args:
    uv run pytest {{args}}

# Check formatting and lint. CI runs this recipe too.
lint:
    uv run ruff format --check .
    uv run ruff check .

# Format the code and apply the lint fixes ruff can make.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Show the gnl containers.
status:
    docker ps --all --filter name=gnl- --format 'table {{"{{.Names}}"}}\t{{"{{.Status}}"}}\t{{"{{.Ports}}"}}'

# Import the S18 and S17 workbooks from tests/data into the running backend, S18 first.
seed api="http://localhost:5002" token="devtoken":
    #!/usr/bin/env bash
    set -euo pipefail
    access=$(curl -fsS -X POST "{{ api }}/login" -H 'Content-Type: application/json' \
        -d "{\"token\": \"{{ token }}\"}" | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')
    for f in tests/data/GNL_S18_export_v2.xlsx tests/data/GNL_S17_export_v2.xlsx; do
        curl -fsS -X POST "{{ api }}/import?create_new=true" -H "Authorization: Bearer $access" -F "file=@$f"; echo
    done
