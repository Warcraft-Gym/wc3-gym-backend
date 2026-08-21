# GNL Backend

FastAPI REST API for the GNL (Gym Newbie League) esports platform providing JWT-authenticated endpoints for user management, team operations, match scheduling, series tracking, and fantasy betting.

## Prerequisites

- **uv** - [Install uv](https://docs.astral.sh/uv/getting-started/installation/) - manages the Python version, the virtual environment, and the dependencies; new to uv? See the [getting started guide](https://docs.astral.sh/uv/getting-started/)
- **Docker Desktop** - [Install Docker](https://www.docker.com/products/docker-desktop)
- **Visual Studio Code** - [Download VS Code](https://code.visualstudio.com/)
- **VS Code Extensions:**
  - Docker (Microsoft)
  - Python (Microsoft)
- **MySQL 5.7.x** - Either:
  - Local MySQL installation, OR
  - MySQL Docker container (recommended)

## MySQL Setup

### Option 1: MySQL Docker Container (Recommended)

Run MySQL in a Docker container:

```bash
docker run -d \
  --name gnl-mysql \
  -e MYSQL_ROOT_PASSWORD=root_password \
  -e MYSQL_DATABASE=GYM_BACKEND \
  -e MYSQL_USER=gym_user \
  -e MYSQL_PASSWORD=gym_user \
  -p 3306:3306 \
  mysql:5.7.41
```

This creates a MySQL 5.7 container accessible at `localhost:3306`.

### Option 2: Local MySQL Installation

If you have MySQL installed locally:
1. Create database: `CREATE DATABASE GYM_BACKEND;`
2. Create user: `CREATE USER 'gym_user'@'localhost' IDENTIFIED BY 'your_password';`
3. Grant privileges: `GRANT ALL PRIVILEGES ON GYM_BACKEND.* TO 'gym_user'@'localhost';`

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

`.env` is committed and holds the values that are not secret: `TOKEN_TIME`, `REFRESH_TOKEN_TIME`, `CURRENT_WC3_SEASON` and `W3C_URL`. `create_app` calls `load_dotenv`, so those arrive on their own. The rest are passed in.

**Key environment variables:**

```bash
DB_URL="mysql+pymysql://gym_user:gym_user@host.docker.internal:3306/GYM_BACKEND"
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
| `DB_URL` | MySQL connection string. Use `host.docker.internal` to connect from Docker container to host machine's MySQL | `mysql+pymysql://gym_user:gym_user@host.docker.internal:3306/GYM_BACKEND` |
| `ADMIN_TOKEN` | Secret token for admin API access (used by Discord bot and admin UI) | `this_is_my_token` |
| `JWT_SECRET_KEY` | Secret key for JWT token signing (generate with `openssl rand -hex 32`) | 64-character hex string |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` or `HS512` |
| `BOT_CLIENT_TOKEN` | Authentication token for Discord bot webhooks | 64-character hex string |
| `FRONTEND_URL` | Admin frontend URL for CORS configuration | `http://localhost:5003` |
| `BOT_WEBHOOK_URL` | Discord bot webhook endpoint for series updates | `http://host.docker.internal:3001/webhook/series-updated` |

**Important Notes:**
- `host.docker.internal` is a special DNS name that resolves to the host machine from within a Docker container
- If MySQL is running locally (not in Docker), use `host.docker.internal:3306`
- If MySQL is in another Docker container on the same network, use the container name instead
- Generate secure tokens using: `openssl rand -hex 32` or `python -c "import secrets; print(secrets.token_hex(32))"`

## Running the Application

### Using just (Recommended)

[just](https://github.com/casey/just) is a command runner. It reads recipes from the `justfile` in the repository root. The dev dependencies install it (PyPI package `rust-just`), so after `uv sync` no separate install is needed — run recipes with `uv run just`:

```bash
uv run just             # list the recipes
uv run just up          # build the image, start MySQL and the backend in Docker
uv run just restart     # start the containers again after a stop
uv run just logs        # follow the backend log
uv run just status      # show the gnl containers
uv run just down        # stop the containers
uv run just test        # run the tests, as CI runs them
uv run just lint        # check formatting and lint, as CI runs them
uv run just fmt         # apply the formatting and lint fixes
uv run just db-status   # show the revision the database is on
uv run just migrate     # bring a database up to date by hand
uv run just revision    # write a migration for the current models
```

`up` covers the full MySQL setup from above: on first use it creates the `gnl-net` Docker network and the `gnl-mysql` container with a named volume (`gnl-mysql-data`), so the database survives `down` and container removal. It then builds the image and starts it on port 5002. Run it again after a code change to rebuild and restart the backend.

The image is tagged `gnl-backend:local`. The tag means what it says: `just up` builds it from the working tree for use on this machine, and nothing pushes it to a registry. A deployment builds and names its own image, so treat `gnl-backend:local` as a local name only and do not read it as a stage of a release.

`up` replaces the backend container, which is what makes it the recipe for a code change. `restart` starts the containers that are already there, which is what a stopped Docker Desktop leaves behind. Neither loses the database: the data is in the `gnl-mysql-data` volume.

The container starts with development-only values (`ADMIN_TOKEN=devtoken`, `JWT_SECRET_KEY=devsecret`). Log in with `devtoken`. Do not use these values outside local development. The backend accepts connections about 30 seconds after `up` returns.

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
  -e DB_URL="mysql+pymysql://gym_user:gym_user@host.docker.internal:3306/GYM_BACKEND" \
  -e ADMIN_TOKEN="your-token" \
  -e JWT_SECRET_KEY="your-secret" \
  -e JWT_ALGORITHM="HS256" \
  eashibby/gnl_backend:latest
```

## Database Migrations

Alembic owns the database structure. The container runs `alembic upgrade head` once at start, before the server, so the application itself never creates or changes a table.

```bash
export DB_URL="mysql+pymysql://gym_user:gym_user@localhost:3306/GYM_BACKEND"

uv run alembic upgrade head        # bring the database up to date
uv run alembic current             # show the revision the database is on
uv run alembic history             # list the revisions
```

The justfile wraps these as `just migrate`, `just db-status` and `just revision`, each taking the same URL as an optional argument, so `just db-status` answers the everyday question without exporting anything.

### DB_URL names the same database twice

`DB_URL` is one variable with two correct values, and picking the wrong one is the usual reason a command cannot connect:

| Where the command runs | Host to use | Why |
|---|---|---|
| Inside a container on `gnl-net` | `gnl-mysql:3306` | Docker resolves the container name on that network |
| On the host, or in an IDE | `localhost:3306` | reaches the port `gnl-mysql` publishes |
| In a container, MySQL on the host | `host.docker.internal:3306` | Docker Desktop's name for the host |

A container started with the `localhost` form will not find MySQL, because `localhost` inside a container is that container. A container started with the `gnl-mysql` form but no `--network gnl-net` will not find it either, because the name only resolves on that network. The justfile holds both forms as `container_db_url` and `host_db_url` and passes the right one, which is the reason to prefer the recipes over typing the commands.

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

**The migration step belongs to the container, so run one backend container per database.** The command starts `alembic upgrade head` and then the server, which is once per container however many workers the server runs. Two containers started together against the same database would run it at the same time, and Alembic does not lock MySQL. To serve from more than one container, run the migration as its own step first and give the containers the server command alone:

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
    -e REFRESH_TOKEN_TIME=1440 \
    gnl-backend:local \
    uvicorn --factory app.main:create_app --host 0.0.0.0 --port 5002
```

Both commands need the network that reaches MySQL, and both need `DB_URL` in the form that resolves there — see the table above. The server command needs the rest of the variables too. Without them the container still starts and still serves, and every admin login answers 401, because `ADMIN_TOKEN` is read per request and an unset one matches no token. Read the variable table before deploying rather than after.

`gnl-backend:local` stands in for the image here because this repository builds no other. A deployment substitutes its own image name.

This is where the deployment differs from the official FastAPI template, which runs `alembic upgrade head` from a `prestart` step of its own and leaves the container command as the server alone. That shape is the right destination. Today there is no compose file and no deploy pipeline in this repository — CI runs lint and tests only — so the single `docker run` carries both, and the commands above are what splitting them looks like by hand.

## Troubleshooting

### Backend Can't Connect to MySQL

**Symptom:** Database connection errors on startup

**Solutions:**
1. Verify MySQL is running: `docker ps` (for Docker) or `netstat -an | findstr 3306` (for local)
2. Test connection: `mysql -h 127.0.0.1 -u gym_user -p`
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
├── justfile               # The everyday commands
├── .env                   # Committed configuration that is not secret
├── tests/                 # pytest suite
├── app/
│   ├── main.py            # The application factory, create_app
│   ├── exceptions.py      # Shared exception types
│   ├── api/
│   │   ├── main.py        # Collects the routers
│   │   ├── deps.py        # Dependencies: auth guards, service instances
│   │   └── routes/        # One module per API area
│   ├── core/
│   │   ├── db.py          # Engine and session factory
│   │   └── security.py    # Token minting and validation
│   ├── services/          # One service per entity
│   ├── models/            # SQLModel table models and their API schemas
│   └── utils/             # Utility functions
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

## List routes and paging

The list routes take `limit` (1 to 500, default 500) and `offset` (>= 0, default 0) query parameters. A limit outside that range answers 422. The page is ordered by `id`, and both values go into the SQL statement, so a large table never becomes a large answer. `tests/test_paging.py` names every paged route.

Six routes carry the total row count in an `X-Total-Count` response header, which CORS exposes to browsers. A client reads the header, then walks the pages with `limit` and `offset`. The count holds for the whole set the route answers, not for the page.

| Route | Default page size |
| --- | --- |
| `GET /users` | 500 |
| `GET /fantasy/teams` | 500 |
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

`GET /koth/events`, `/config/settings`, the export and import routes and `routes/scores.py` answer full lists: their clients read the whole set.

The list routes answer reduced payloads: every JSON key stays, and the collections nested inside embedded objects answer `[]`. The single-row routes keep the full graph. `tests/test_memory_budget.py` pins the peak memory of the bets list, and `tests/test_query_budget.py` pins the statement counts of the list queries.
