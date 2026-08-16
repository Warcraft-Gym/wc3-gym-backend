# Local dev stack: MySQL and the backend, both in Docker.
# just installs with the dev dependencies; run recipes with `uv run just <recipe>`.

set shell := ["bash", "-euo", "pipefail", "-c"]

# The tag `up` builds from the working tree. It is a local development
# image and nothing publishes it, so a deployment names its own image.
image := "gnl-backend:local"

# The same database under its two names. Which one is right depends on
# where the command runs, and that is the usual reason a connection fails.
# The backend container reaches MySQL over the gnl-net network by container
# name; a command on the host reaches it through the published port.
container_db_url := "mysql+pymysql://gym_user:gym_user@gnl-mysql:3306/GYM_BACKEND"
host_db_url := "mysql+pymysql://gym_user:gym_user@localhost:3306/GYM_BACKEND"

default:
    @just --list

# Start MySQL, then build and start the backend on port 5002.
up:
    #!/usr/bin/env bash
    set -euo pipefail

    docker network inspect gnl-net >/dev/null 2>&1 || docker network create gnl-net

    if docker container inspect gnl-mysql >/dev/null 2>&1; then
        docker start gnl-mysql
    else
        docker run -d --name gnl-mysql --network gnl-net \
            -e MYSQL_ROOT_PASSWORD=root_password \
            -e MYSQL_DATABASE=GYM_BACKEND \
            -e MYSQL_USER=gym_user \
            -e MYSQL_PASSWORD=gym_user \
            -p 3306:3306 \
            -v gnl-mysql-data:/var/lib/mysql \
            mysql:5.7.41
    fi

    echo "Waiting for MySQL..."
    for _ in $(seq 1 30); do
        if docker exec gnl-mysql mysqladmin ping -u gym_user -pgym_user --silent 2>/dev/null; then
            break
        fi
        sleep 2
    done

    docker build -t {{image}} {{justfile_directory()}}
    docker rm -f gnl-backend >/dev/null 2>&1 || true
    docker run -d --name gnl-backend --network gnl-net -p 5002:5002 \
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

    echo
    echo "Backend: http://localhost:5002/docs (ready in ~30s, admin token: devtoken)"

# Start the stopped containers again, MySQL first. Use after Docker Desktop restarts.
restart:
    docker start gnl-mysql
    docker start gnl-backend

# Follow the backend log, where the migration and the server both write.
logs *args:
    docker logs --follow --tail 50 {{args}} gnl-backend

# Bring a database up to date by hand. The backend container does this at every start.
migrate db_url=host_db_url:
    DB_URL="{{db_url}}" uv run alembic upgrade head

# Write a migration for the current models. Read it before committing: autogenerate also drops.
revision message db_url=host_db_url:
    DB_URL="{{db_url}}" uv run alembic revision --autogenerate -m "{{message}}"

# Show the revision a database is on, and the revisions that exist.
db-status db_url=host_db_url:
    DB_URL="{{db_url}}" uv run alembic current
    DB_URL="{{db_url}}" uv run alembic history

# Drop every table, then build the schema again. Deletes all data.
db-reset db_url=host_db_url:
    DB_URL="{{db_url}}" uv run alembic downgrade base
    DB_URL="{{db_url}}" uv run alembic upgrade head

# Stop the backend and MySQL, keeping the data. A missing container is not an error.
down:
    docker stop gnl-backend gnl-mysql 2>/dev/null || true

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
