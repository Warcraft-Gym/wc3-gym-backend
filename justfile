# Local dev stack: MySQL and the backend, both in Docker.
# just installs with the dev dependencies; run recipes with `uv run just <recipe>`.

set shell := ["bash", "-euo", "pipefail", "-c"]

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

    docker build -t gnl-backend:local {{justfile_directory()}}
    docker rm -f gnl-backend >/dev/null 2>&1 || true
    docker run -d --name gnl-backend --network gnl-net -p 5002:5002 \
        -e DB_URL="mysql+pymysql://gym_user:gym_user@gnl-mysql:3306/GYM_BACKEND" \
        -e ADMIN_TOKEN=devtoken \
        -e JWT_SECRET_KEY=devsecret \
        -e JWT_ALGORITHM=HS256 \
        -e TOKEN_TIME=60 \
        -e REFRESH_TOKEN_TIME=1440 \
        -e BOT_CLIENT_TOKEN=dummy \
        -e BOT_WEBHOOK_URL=http://localhost:9999 \
        -e FRONTEND_URL=http://localhost:5003 \
        gnl-backend:local

    echo
    echo "Backend: http://localhost:5002/docs (ready in ~30s, admin token: devtoken)"

# Stop the backend and MySQL. The data stays in the gnl-mysql-data volume.
down:
    docker stop gnl-backend gnl-mysql

# Show the gnl containers.
status:
    docker ps --all --filter name=gnl- --format 'table {{"{{.Names}}"}}\t{{"{{.Status}}"}}\t{{"{{.Ports}}"}}'
