# GNL Backend

FastAPI REST API for the GNL (Gym Newbie League) esports platform providing JWT-authenticated endpoints for user management, team operations, match scheduling, series tracking, and fantasy betting.

## Prerequisites

- **uv** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/) - manages the Python version, the virtual environment, and the dependencies; new to uv? See the [getting started guide](https://docs.astral.sh/uv/getting-started/)
- **Docker Desktop** - [Install Docker](https://www.docker.com/products/docker-desktop)
- **Visual Studio Code** - [Download VS Code](https://code.visualstudio.com/)
- **VS Code Extensions:**
  - Docker (Microsoft)
  - Python (Microsoft)
- **PostgreSQL 15+** - Either:
  - PostgreSQL Docker container (recommended for development), OR
  - A Supabase project

## PostgreSQL Setup

### Option 1: PostgreSQL Docker Container (Recommended)

Run PostgreSQL in a Docker container (`just up` does this for you):

```bash
docker run -d \
  --name gnl-postgres \
  -e POSTGRES_DB=gym_backend \
  -e POSTGRES_USER=gym_user \
  -e POSTGRES_PASSWORD=gym_user \
  -p 5432:5432 \
  postgres:17
```

This creates a PostgreSQL 17 container accessible at `localhost:5432`.

### Option 2: Supabase

Use the **pooler** connection string from the Supabase dashboard (Connect → Session pooler), not the direct `db.<ref>.supabase.co` host: the direct host resolves to IPv6 only, which Vercel and most home networks cannot reach. The pooler user is `postgres.<ref>`, the host prefix `aws-<n>` differs per region (us-east-1 is `aws-0`, eu-west-1 was `aws-1`), the password must be percent-encoded, and the SQLAlchemy scheme is `postgresql+psycopg`:

```bash
DB_URL="postgresql+psycopg://postgres.<ref>:<password>@aws-<n>-<region>.pooler.supabase.com:5432/postgres?sslmode=require"
```

Port 5432 is the session pooler, which behaves like a direct connection and is the one to use for `alembic upgrade head` and for a long-lived server. Port 6543 is the transaction pooler for serverless functions; it needs `connect_args={"prepare_threshold": None}` in `init_engine`, which is not set today.

## Where the backend runs

One code, two mechanisms, three places you can reach from a laptop. Docker runs the image with `alembic upgrade head` at every start; Vercel runs `api/index.py` as a function and migrates in the build.

**One just module per place.** A recipe exists in a module only if it makes sense there, so `just azure --list` is the list of what the box supports, and nothing else. Production is EAShibby's box, reached only through Portainer, so it has no module and no recipes.

| | `just local` | `just azure` | `just vercel` |
|---|---|---|---|
| Where | Docker on this machine | the Terraform staging box, over SSH | the Vercel project |
| Runs | the image, built from your working tree | the published GHCR image | `api/index.py` as a function |
| `deploy` | — build with `up` | pins the box to an image tag | `vercel deploy`, prod or a preview |
| `logs`, `status` | `docker logs`, `docker ps` | `compose logs`, `compose ps` over SSH | `vercel logs`, `vercel ls` |
| `migrate`, `alembic` | against `LOCAL_DB_URL` | inside the backend container | against the pooler URL |
| `seed` | the private seed repo | the seed repo, loaded in the container | the seed repo |
| Only here | `up`, `down`, `restart`, `psql`, `serve`, `import-xlsx`, `revision`, `reset` | — | `list`, `drop` (the preview databases), `url` |

`just vercel` takes an environment, `prod` by default: `just vercel migrate` is production, `just vercel migrate staging` is the preview project. A push to `main` deploys production on its own; `just vercel deploy` is the same deploy from a working tree.

The values come from `.env`, copied from `.env.example` and gitignored: `LOCAL_DB_URL`, `VERCEL_PROD_DB_URL`, `VERCEL_STAGING_DB_URL`, and `AZURE_STAGING_HOST`, which is `terraform -chdir=infra output -raw fqdn` in the gym-root workspace.

The gym-root workspace owns what spans two repositories: Terraform for the Azure box, the box files, and the frontend. Its `just azure deploy` calls `just azure deploy <tag>` here for the backend half.

## Deploying to Vercel

Vercel serves `api/index.py`, which imports the same application the container runs. Set `DB_URL`, `JWT_SECRET_KEY`, `ADMIN_TOKEN`, `BOT_CLIENT_TOKEN` and `FRONTEND_URL` in the project settings; the deployment reads no `.env` file.

The production build runs `alembic upgrade head` (`vercel.json`) before the new code is promoted, so a migration that fails stops the deploy. Previews run against the staging Supabase project: the shared `wc3gym_staging` database, or a branch's own copy when the branch adds a migration. How and why is in [docs/PREVIEW-DATABASES.md](docs/PREVIEW-DATABASES.md). The old code keeps serving while the build runs, so every migration must work with the code before it and after it: add columns nullable or with a default, drop a column only after the code that read it has shipped.

Use the session pooler on port 5432 for `DB_URL`. Port 6543 is the transaction pooler; it needs `connect_args={"prepare_threshold": None}` in `init_engine`, which is not set, so a `DB_URL` on 6543 fails on the second request.

A full-season `POST /import` takes longer than the Vercel function timeout. Import a season from a machine that runs the server itself, or against the pooler URL directly.

## Deploying to a Docker host

The Azure VM runs the same image next to Postgres under Docker Compose. This is the stack with the values a deployment has to fill in; the secrets belong in the stack environment (Portainer, a `.env` next to the file), not in the file.

```yaml
# GNL prod stack on Postgres. Same shape as gnl_docker_compose/docker-compose.yml with the
# database swapped and the backend mount removed. Put the secrets in Portainer's stack env, not here.
name: gnl

services:
  gnl-postgres:
    container_name: gnl-postgres
    image: postgres:17-alpine
    restart: always
    command: ["postgres", "-c", "log_min_duration_statement=200", "-c", "effective_cache_size=512MB"]
    environment:
      POSTGRES_DB: GYM_BACKEND
      POSTGRES_USER: gnl_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      # Case-insensitive text order, as MySQL had. Only read on first start of an empty volume.
      POSTGRES_INITDB_ARGS: --locale-provider=icu --icu-locale=en-US
    volumes:
      - gnl-pgdata:/var/lib/postgresql/data
    networks:
      - gnl-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gnl_user -d GYM_BACKEND"]
      interval: 10s
      timeout: 5s
      retries: 30

  gnl-backend:
    container_name: backend
    image: eashibby/gnl_backend:latest
    restart: always
    environment:
      - DB_URL=postgresql+psycopg://gnl_user:${DB_PASSWORD}@gnl-postgres:5432/GYM_BACKEND
      - ADMIN_TOKEN=${ADMIN_TOKEN}
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - JWT_ALGORITHM=HS256
      - BOT_CLIENT_TOKEN=${BOT_CLIENT_TOKEN}
      - FRONTEND_URL=${FRONTEND_URL}
      - LOG_LEVEL=INFO
    ports:
      - 5002:5002
    depends_on:
      gnl-postgres:
        condition: service_healthy
    networks:
      - gnl-network

  gnl-discord-bot:
    container_name: discord-bot
    image: eashibby/gnl_discord_bot:latest
    restart: always
    environment:
      - DISCORD_TOKEN=${DISCORD_TOKEN}
      - BACKEND_URL=http://backend:5002
      - ADMIN_TOKEN=${ADMIN_TOKEN}
    depends_on:
      - gnl-backend
    networks:
      - gnl-network

  gnl-admin-ui:
    container_name: admin-ui
    image: eashibby/gnl_admin_ui:latest
    restart: always
    ports:
      - "5003:5003"
    depends_on:
      - gnl-backend
    networks:
      - gnl-network

volumes:
  gnl-pgdata:

networks:
  gnl-network:
    driver: bridge
```

What this changes against a MySQL stack of the original app:

- `DB_URL` uses the `postgresql+psycopg` scheme, port 5432 and the Postgres service name.
- The backend mounts no volume over `/app`. The image carries the code, so a new image is a new version; a volume there would shadow it.
- The container runs `alembic upgrade head` before the server, so it creates the schema on an empty database. `depends_on` with `service_healthy` keeps it from starting before Postgres answers.
- `BOT_CLIENT_TOKEN` and `FRONTEND_URL` are read; without them the bot's public routes and the browser's CORS requests are refused.
- `POSTGRES_INITDB_ARGS` picks the ICU collation, which orders text without regard to case as MySQL did. It is read once, on the first start of an empty volume.
- The data moves by workbook, not by dump: export every season from the old app, `POST /import` each here, newest season first. Then set the `settings` rows and upload the team icons.
- A backup is one command: `docker compose exec -T gnl-postgres pg_dump -U gnl_user -Fc GYM_BACKEND > gnl.dump`; restore with `pg_restore -U gnl_user -d GYM_BACKEND < gnl.dump` on the same service.

## Season workbooks

`POST /export` writes one season as an xlsx and `POST /import` reads it back. The pair is the migration path off the MySQL app: export each season there, import each here.

The import writes no ids of its own. A season matches by name, a player by battle tag, a team by name and a series by its match and its two players, so the Postgres sequences keep counting from the rows that are already stored.

`tests/data/` holds the real S17 and S18 exports; `just import-xlsx` imports both into a running backend (S18 first, so shared players keep the newer attributes) and the suite round-trips them.

Ten sheets travel. These tables do not: `settings`, `w3cstats`, `player_career_stats`, `user_season_signup`, `koth_events`, `koth_matches`, `koth_match_participants`, `koth_signups`, `draft_series`, and the `icon` column of `teams`. Carry those over another way.

## Project Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd backend
```

### 2. Install Dependencies

```bash
uv sync
```

This one command installs a compatible Python, creates `.venv`, and installs the dependencies from `uv.lock`, including the dev group (pytest). No activation needed: run tools with `uv run <command>`.

VS Code will prompt to select `.venv` as the workspace interpreter - click "Yes".

Dependencies live in `pyproject.toml`: runtime packages under `[project] dependencies`, development-only packages under `[dependency-groups] dev`. After editing either list, run `uv sync` again and commit the updated `uv.lock`. The Docker image installs from the same `uv.lock`, so one edit covers both local development and deployment.

### 3. Know the environment variables

The backend reads its configuration from the environment. `just up` passes development-only values, so nothing here needs setting by hand to run the project locally. Read this table before deploying, and when a container starts but behaves oddly.

`.env` is gitignored; copy `.env.example` to `.env` and fill in what you use. `create_app` calls `load_dotenv`, so its values arrive on their own; each has a default in the code. The deployment secrets are passed in by the stack.

More values live in the `settings` table, not the environment, and are edited on the admin Config page: `w3c_url` (wins over the `W3C_URL` variable when present), `current_w3c_season` (the w3champions season the MMR columns read; when the row is missing the backend takes the newest season from w3champions), `KOTH_NIGHTBOT_TOKEN`, and `current_gnl_season` (the season the captain check and the role sync read; when the row is missing they take the newest season). The Discord roles the app owns are rows of `discord_role_binding`, not settings, and the site admins are rows of `admin_grant`, managed under Config -> Access with `ADMIN_DISCORD_IDS` as the bootstrap. Discord grants no site admin: the guild owner, a role with the ADMINISTRATOR bit and the `admin_role` setting all read as members, and `admin_role` stays a setting because the Discord bot reads it for its own commands. `GET /config/w3c` shows the URL and season the backend resolved.

**Key environment variables:**

```bash
DB_URL="postgresql+psycopg://gym_user:gym_user@host.docker.internal:5432/gym_backend"
ADMIN_TOKEN="your-admin-token-here"
JWT_SECRET_KEY="your-secret-key-here"
JWT_ALGORITHM="HS256"
BOT_CLIENT_TOKEN="your-bot-client-token-here"
FRONTEND_URL="http://localhost:5003"
BOT_WEBHOOK_URL="http://host.docker.internal:3001/webhook/series-updated"
```

**Environment Variable Explanations:**

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_URL` | PostgreSQL connection string with the `postgresql+psycopg` scheme. Use `host.docker.internal` to connect from a Docker container to the host machine's PostgreSQL | `postgresql+psycopg://gym_user:gym_user@host.docker.internal:5432/gym_backend` |
| `ADMIN_TOKEN` | Secret token for admin API access (used by Discord bot and admin UI) | `this_is_my_token` |
| `JWT_SECRET_KEY` | Secret key for JWT token signing (generate with `openssl rand -hex 32`) | 64-character hex string |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` or `HS512` |
| `BOT_CLIENT_TOKEN` | Authentication token for Discord bot webhooks | 64-character hex string |
| `FRONTEND_URL` | Admin frontend URL for CORS configuration | `http://localhost:5003` |
| `BOT_WEBHOOK_URL` | Discord bot webhook endpoint for series updates; when unset, the notification is skipped | `http://host.docker.internal:3001/webhook/series-updated` |
| `TOKEN_TIME` | Access token lifetime in minutes | `60` |
| `W3C_URL` | w3champions API base | `https://website-backend.w3champions.com/api` |
| `LOG_LEVEL` | Python log level | `INFO` |
| `CLERK_SECRET_KEY` | Clerk instance secret; verifies the session token and reads the account's Discord token | `sk_test_...` |
| `CLERK_AUTHORIZED_PARTIES` | Comma-separated origins Clerk accepts the session from | `http://localhost:5173` |
| `DISCORD_GUILD_ID` | The WC3 Gym Discord server; an account outside it logs in as a guest and reaches no player route | `316390574808760322` |
| `ADMIN_DISCORD_IDS` | Comma-separated Discord ids that administer the site with no grant row and cannot be revoked; the bootstrap for Config -> Access | `220202568490418179` |
| `DISCORD_BOT_TOKEN` | Optional bot token; when set, the app mirrors the roles of `discord_role_binding` into the guild and Config -> Discord roles reports the difference. Unset, every sync is a no-op | `MTIz...` |

**Important Notes:**
- `host.docker.internal` is a special DNS name that resolves to the host machine from within a Docker container
- If PostgreSQL is running locally (not in Docker), use `host.docker.internal:5432`
- If PostgreSQL is in another Docker container on the same network, use the container name instead
- Generate secure tokens using: `openssl rand -hex 32` or `python -c "import secrets; print(secrets.token_hex(32))"`

## Running the Application

### Using just (Recommended)

[just](https://github.com/casey/just) is a command runner. It reads recipes from the `justfile` in the repository root, which holds the code recipes and one module per place the backend runs, under `just/`. The dev dependencies install it (PyPI package `rust-just`), so after `uv sync` no separate install is needed — run recipes with `uv run just`:

```bash
uv run just                          # list the recipes and the modules
uv run just test                     # run the tests, as CI runs them
uv run just lint                     # check formatting and lint, as CI runs them
uv run just fmt                      # apply the formatting and lint fixes

uv run just up                       # build the image, start Postgres and the backend in Docker
uv run just down                     # stop the containers
uv run just logs                     # follow the backend log
uv run just psql                     # open psql on the database
uv run just serve                    # run the app as Vercel runs it, from the working tree
uv run just local seed               # migrate, then load the private seed repo
uv run just local revision "message" # write a migration for the current models
uv run just local alembic current    # any alembic command against the database

uv run just azure deploy sha-77f9280a  # pin the staging box to a published image tag
uv run just azure logs                 # follow the backend log on the box
uv run just azure seed                 # migrate the box, then load the seed repo

uv run just vercel deploy            # deploy the working tree to production
uv run just vercel migrate staging   # migrate the preview project
uv run just vercel list              # list the preview databases
```

`up`, `down`, `restart`, `logs`, `status`, `psql` and `serve` are aliases for the `local` recipes of the same name, because that is where the daily work happens. `just local --list`, `just azure --list` and `just vercel --list` show what each place supports; "Where the backend runs" above is the table.

`up` covers the full PostgreSQL setup from above: on first use it creates the `gnl-net` Docker network and the `gnl-postgres` container with a named volume (`gnl-postgres-data`), so the database survives `down` and container removal. It then builds the image and starts it on port 5002. Run it again after a code change to rebuild and restart the backend.

The image is tagged `gnl-backend:local`. The tag means what it says: `just up` builds it from the working tree for use on this machine, and nothing pushes it to a registry. A deployment builds and names its own image, so treat `gnl-backend:local` as a local name only and do not read it as a stage of a release.

`up` replaces the backend container, which is what makes it the recipe for a code change. `restart` starts the containers that are already there, which is what a stopped Docker Desktop leaves behind. Neither loses the database: the data is in the `gnl-postgres-data` volume.

The container starts with development-only values (`ADMIN_TOKEN=devtoken`, `JWT_SECRET_KEY=devsecret`). Log in with `devtoken`. Do not use these values outside local development. The backend accepts connections about 30 seconds after `up` returns.

`serve` is the other way to run the code: `uvicorn api.index:app` from the working tree, with `DB_URL` from `.env`, no image and no migration at start. It is what Vercel runs, so use it to reproduce a Vercel-only fault. Migrate first with `just local migrate`.

If `just` is installed system-wide, the `uv run` prefix is optional.

### Accessing the Application

- **Backend API:** http://localhost:5002
- **API docs (Swagger UI):** http://localhost:5002/docs
- **OpenAPI document:** http://localhost:5002/openapi.json

### Manual Docker Commands

The image name is the only difference from what `just up` runs. `gnl-backend:local` is the tag `up` builds for this machine; `eashibby/gnl_backend:latest` is the published name a deployment pulls. One Dockerfile builds both, so the tag records where an image is meant to run and nothing else.

```bash
# Build image
docker build -t eashibby/gnl_backend:latest .

# Run container
docker run -d \
  -p 5002:5002 \
  -e DB_URL="postgresql+psycopg://gym_user:gym_user@host.docker.internal:5432/gym_backend" \
  -e ADMIN_TOKEN="your-token" \
  -e JWT_SECRET_KEY="your-secret" \
  -e JWT_ALGORITHM="HS256" \
  eashibby/gnl_backend:latest
```

## Database Migrations

Alembic owns the database structure. The container runs `alembic upgrade head` once at start, before the server, so the application itself never creates or changes a table.

```bash
export DB_URL="postgresql+psycopg://gym_user:gym_user@localhost:5432/gym_backend"

uv run alembic upgrade head        # bring the database up to date
uv run alembic current             # show the revision the database is on
uv run alembic history             # list the revisions
```

Each place wraps these in its own module: `just local migrate`, `just local alembic history`, `just vercel migrate staging`, `just azure migrate`. The URLs come from `.env` (`LOCAL_DB_URL`, `VERCEL_PROD_DB_URL`, `VERCEL_STAGING_DB_URL`), gitignored, copied from `.env.example`; `just vercel url staging` prints one. The Azure box has no URL reachable from a laptop, so its recipes run alembic and the seed script inside the backend container over SSH.

### DB_URL names the same database twice

`DB_URL` is one variable with two correct values, and picking the wrong one is the usual reason a command cannot connect:

| Where the command runs | Host to use | Why |
|---|---|---|
| Inside a container on `gnl-net` | `gnl-postgres:5432` | Docker resolves the container name on that network |
| On the host, or in an IDE | `localhost:5432` | reaches the port `gnl-postgres` publishes |
| In a container, PostgreSQL on the host | `host.docker.internal:5432` | Docker Desktop's name for the host |

A container started with the `localhost` form will not find PostgreSQL, because `localhost` inside a container is that container. A container started with the `gnl-postgres` form but no `--network gnl-net` will not find it either, because the name only resolves on that network. The justfile holds both forms as `container_db_url` and `host_db_url` and passes the right one, which is the reason to prefer the recipes over typing the commands.

After changing a model, write the migration for it:

```bash
uv run alembic revision --autogenerate -m "Add the column"
```

Read what autogenerate wrote before committing it. It compares the models against the connected database and will happily drop a column the models no longer declare.

**A database that already holds the tables** — the production one, and any development database made before this repository had migrations — needs no work. The first revision sees the tables, creates nothing and records itself, so `alembic upgrade head` is safe to run against it.

### Stopping and starting a container

Starting a container again runs its command again, so `alembic upgrade head` runs at every start. It is the migration command that repeats, not the migration. Alembic reads the revision recorded in the `alembic_version` table, finds the database already at head, and emits no DDL, so the tables and the data are untouched. There is nothing to clean up between a `docker stop` and a `docker start`, and `just restart` is safe to run as often as you like.

The log tells the two apart. A start with work to do names the revision it applies:

```
INFO  [alembic.runtime.migration] Running upgrade  -> 658616cf0c2b, Create the initial schema
```

A start with nothing to do logs the two context lines and goes straight to the server, with no `Running upgrade` line. `just logs` shows this.

### Serving from more than one container

**The migration step belongs to the container, so run one backend container per database.** The command starts `alembic upgrade head` and then the server, which is once per container however many workers the server runs. Two containers started together against the same database would run it at the same time, and Alembic does not lock the database. To serve from more than one container, run the migration as its own step first and give the containers the server command alone:

```bash
# The migration, once, and wait for it to finish before starting any server.
docker run --rm --network gnl-net -e DB_URL="$DB_URL" gnl-backend:local alembic upgrade head

# Then the servers, which now only serve.
docker run -d --network gnl-net -p 5002:5002 \
    -e DB_URL="$DB_URL" \
    -e ADMIN_TOKEN="$ADMIN_TOKEN" \
    -e JWT_SECRET_KEY="$JWT_SECRET_KEY" \
    -e JWT_ALGORITHM=HS256 \
    -e TOKEN_TIME=60 \
    gnl-backend:local \
    uvicorn --factory app.main:create_app --host 0.0.0.0 --port 5002
```

Both commands need the network that reaches PostgreSQL, and both need `DB_URL` in the form that resolves there — see the table above. The server command needs the rest of the variables too. Without them the container still starts and still serves, and every admin login answers 401, because `ADMIN_TOKEN` is read per request and an unset one matches no token. Read the variable table before deploying rather than after.

`gnl-backend:local` stands in for the image here because this repository builds no other. A deployment substitutes its own image name.

This is where the deployment differs from the official FastAPI template, which runs `alembic upgrade head` from a `prestart` step of its own and leaves the container command as the server alone. That shape is the right destination. Today there is no compose file and no deploy pipeline in this repository — CI runs lint and tests and publishes the image — so the single `docker run` carries both, and the commands above are what splitting them looks like by hand.

## Troubleshooting

### Backend Can't Connect to PostgreSQL

**Symptom:** Database connection errors on startup

**Solutions:**
1. Verify PostgreSQL is running: `docker ps` (for Docker) or `netstat -an | findstr 5432` (for local)
2. Test connection: `psql -h 127.0.0.1 -U gym_user -d gym_backend`
3. Ensure `host.docker.internal` is resolving (Windows/Mac Docker Desktop feature)
4. For Linux, use `--add-host=host.docker.internal:host-gateway` in docker run command

### Import Error: No module named 'xyz'

**Solution:** Reinstall the environment
```bash
uv sync
```

### Port 5002 Already in Use

**Solution:** Stop whatever holds the port. The usual cause is the backend container: run `uv run just down`.
```bash
# Find process using port
netstat -ano | findstr :5002

# Kill process (Windows)
taskkill /PID <pid> /F
```

## Project Structure

```
backend/
├── pyproject.toml          # Project metadata and dependencies
├── uv.lock                 # Pinned dependency versions (managed by uv)
├── Dockerfile             # Docker image definition
├── vercel.json            # The Vercel build command, which migrates by environment
├── justfile               # test, lint, fmt, and one module per place the backend runs
├── just/                  # One module per place: local.just, azure.just, vercel.just
├── .env                   # Database URLs and the staging host; gitignored, copy .env.example
├── api/                   # The Vercel entry point and its preview-database choice
├── scripts/               # Database helpers the just recipes call
├── tests/                 # pytest suite
├── app/
│   ├── main.py            # The application factory, create_app
│   ├── api/
│   │   ├── main.py        # Collects the routers
│   │   ├── deps.py        # Dependencies: auth guards, service instances
│   │   └── routes/        # One module per API area
│   ├── core/
│   │   ├── db.py          # Engine and session factory
│   │   ├── security.py    # Token minting and validation
│   │   ├── exceptions.py  # NotFoundError, BadRequestError
│   │   ├── query.py       # The search language of the /search routes
│   │   ├── ordering.py    # sort and order on list statements
│   │   ├── scoring.py     # Series points rule
│   │   ├── career.py      # Career rating rule
│   │   └── fantasy.py     # Fantasy scoring rule
│   ├── services/          # One service per entity; derived.py computes scores at read time
│   └── models/            # SQLModel table models and their API schemas
├── alembic.ini            # Alembic configuration
└── migrations/            # Schema migrations
```

The server calls the factory, so nothing builds an application at import:
`uvicorn --factory app.main:create_app`.

## Development Workflow

1. Make code changes
2. Rebuild and restart with `uv run just up`
3. Test endpoints at http://localhost:5002/docs
4. Read the log with `uv run just logs`

## Tests

```bash
uv run pytest
```

The tests run against a temporary SQLite file and need no database server
and no environment variables. The suite builds that file with
`alembic upgrade head`, the way a deployment does, so every run checks the
migrations as well. See `tests/conftest.py` for the design rules.

To run the same suite against PostgreSQL, point `TEST_DB_URL` at a server
whose user may create databases; the suite drops and creates its own:

```bash
TEST_DB_URL="postgresql+psycopg://gym_user:gym_user@localhost:5432/postgres" uv run pytest
```

## List routes and paging

The list routes take `limit` (1 to 500, default 500) and `offset` (>= 0, default 0) query parameters. A limit outside that range answers 422. The page is ordered by `id`, and both values go into the SQL statement, so a large table never becomes a large answer. `tests/test_paging.py` names every paged route.

Seven routes carry the total row count in an `X-Total-Count` response header, which CORS exposes to browsers. A client reads the header, then walks the pages with `limit` and `offset`. The count holds for the whole set the route answers, not for the page.

| Route | Default page size |
| --- | --- |
| `GET /users` | 500 |
| `GET /fantasy/teams` | 500 |
| `POST /fantasy/teams/search` | 500 |
| `GET /fantasy/bets` | 500 |
| `POST /fantasy/bets/search` | 500 |
| `GET /player-series` | 500 |
| `GET /stats/career` | 500 |

`GET /stats/career` takes an optional `search` string as well, which keeps the rows whose player name or user name holds it, without case. The header counts the kept rows.

Three routes also take `sort` and `order`, both optional. `sort` names one field of the table below and `order` is `asc` (the default) or `desc`. A name outside the table answers 422, and so does any other order. `order` turns the named field around alone: the `id` after it stays ascending, so two requests with the same parameters answer the same pages. Without `sort` the route keeps the order it has always answered, which `tests/test_paging.py` pins per route.

| Route | Sort names |
| --- | --- |
| `POST /fantasy/bets/search` | `id`, `bet_points`, `captain`, `series_id` |
| `GET /player-series` | `date_time`, `week`, `id` |
| `GET /stats/career` | `name`, `mapped`, `rating`, `series_won`, `series_lost`, `series_winrate`, `games_won`, `games_lost`, `games_winrate`, `seasons_played` |

`GET /koth/events`, `/config/settings` and the export and import routes answer full lists: their clients read the whole set.

The list routes answer reduced payloads: every JSON key stays, and the collections nested inside embedded objects answer `[]`. The single-row routes keep the full graph. `tests/test_memory_budget.py` pins the peak memory of the bets list, and `tests/test_query_budget.py` pins the statement counts of the list queries.
