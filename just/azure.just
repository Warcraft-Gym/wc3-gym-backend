# The Azure staging box, over SSH. It runs the published image next to Postgres under Docker Compose,
# so alembic and the seed script run inside the backend container there.
# AZURE_STAGING_HOST in .env is `terraform -chdir=infra output -raw fqdn` in the gym-root workspace.
# Terraform, the box files and the frontend half of a deploy stay in the gym root.

# Recipes run from the repository root, one level up from this file.
set working-directory := '..'

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load

host := env("AZURE_STAGING_HOST", "")
box := "azureuser@" + host
api := "http://" + host + ":5002"
registry_image := "ghcr.io/tanghyd/gnl-backend"

default:
    @just --list azure

# Fail with the fix when AZURE_STAGING_HOST is not set.
_host:
    @[ -n "{{ host }}" ] || { echo "set AZURE_STAGING_HOST in .env: terraform -chdir=infra output -raw fqdn, in the gym root" >&2; exit 1; }

# Pin the box to a published image tag and restart the backend. The frontend line in /opt/gnl/.env is left alone.
deploy tag="staging": _host
    #!/usr/bin/env bash
    set -euo pipefail
    image="{{ registry_image }}:{{ tag }}"
    token=$(curl -fsS "https://ghcr.io/token?scope=repository:tanghyd/gnl-backend:pull&service=ghcr.io" \
        | uv run python -c 'import json, sys; print(json.load(sys.stdin)["token"])')
    code=$(curl -fsS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" \
        -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.v2+json,application/vnd.oci.image.manifest.v1+json' \
        "https://ghcr.io/v2/tanghyd/gnl-backend/manifests/{{ tag }}")
    [ "$code" = "200" ] || { echo "$image is not anonymously pullable (HTTP $code)" >&2; exit 1; }
    ssh {{ box }} bash -s <<REMOTE
    set -euo pipefail
    cd /opt/gnl
    sudo touch .env
    grep -q '^BACKEND_IMAGE=' .env && sudo sed -i 's#^BACKEND_IMAGE=.*#BACKEND_IMAGE=$image#' .env \
        || echo 'BACKEND_IMAGE=$image' | sudo tee -a .env >/dev/null
    sudo docker compose config | grep -q "image: $image" \
        || { echo 'compose.yaml does not read BACKEND_IMAGE from .env; run: just azure sync, in the gym root' >&2; exit 1; }
    sudo docker compose pull -q backend && sudo docker compose up -d backend
    sudo docker image prune -f >/dev/null
    REMOTE
    for _ in $(seq 1 60); do
        curl -fsS "{{ api }}/health" >/dev/null 2>&1 && break
        sleep 3
    done
    curl -fsS "{{ api }}/health"; echo

# Follow the backend log on the box.
logs: _host
    ssh -t {{ box }} "cd /opt/gnl && sudo docker compose logs -f --tail=200 backend"

# Show the health, the pinned image and the backend container.
status: _host
    @echo "api {{ api }}"
    curl -fsS "{{ api }}/health" && echo
    ssh {{ box }} 'grep ^BACKEND_IMAGE /opt/gnl/.env; cd /opt/gnl && sudo docker compose ps backend'

# Bring the database to the latest migration, inside the backend container.
migrate: _host
    ssh {{ box }} 'cd /opt/gnl && sudo docker compose exec -T backend alembic upgrade head'

# Run any alembic command inside the backend container, for example `just azure alembic current`.
alembic *args: _host
    ssh {{ box }} 'cd /opt/gnl && sudo docker compose exec -T backend alembic {{ args }}'

# Migrate, then load the private seed repo. The image carries scripts/seed_db.py, so only the CSVs travel.
seed: _host migrate
    #!/usr/bin/env bash
    set -euo pipefail
    seed=$(mktemp -d)
    trap 'rm -rf "$seed"' EXIT
    just _fetch-seed "$seed"
    if [ -f "$seed/users.csv" ]; then
        tar -C "$seed" -cz . | ssh {{ box }} 'rm -rf /tmp/seed && mkdir /tmp/seed && tar -C /tmp/seed -xz && chmod -R a+rX /tmp/seed && cd /opt/gnl && sudo docker compose run --rm --no-deps -T -v /tmp/seed:/seed backend sh -c "python scripts/seed_db.py /seed \"\$DB_URL\""'
    fi
