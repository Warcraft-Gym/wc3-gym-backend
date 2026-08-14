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

## VS Code Setup

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

### 3. Configure tasks.json

The project uses VS Code tasks for Docker builds and runs. The configuration is in `.vscode/tasks.json`.

**Key environment variables to configure:**

```json
{
  "env": {
    "DB_URL": "mysql+pymysql://gym_user:gym_user@host.docker.internal:3306/GYM_BACKEND",
    "ADMIN_TOKEN": "your-admin-token-here",
    "JWT_SECRET_KEY": "your-secret-key-here",
    "JWT_ALGORITHM": "HS256",
    "BOT_CLIENT_TOKEN": "your-bot-client-token-here",
    "FRONTEND_URL": "http://localhost:5003",
    "BOT_WEBHOOK_URL": "http://host.docker.internal:3001/webhook/series-updated"
  }
}
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

### Using VS Code Docker Tasks

1. Open the **Run and Debug** panel (Ctrl+Shift+D)
2. Select **"docker-run: debug"** from the dropdown
3. Press F5 or click the green play button

This will:
- Build the Docker image (`eashibby/gnl_backend:latest`)
- Start the container with environment variables from tasks.json
- Run uvicorn on port 5002
- Attach debugger for breakpoint support

### Accessing the Application

- **Backend API:** http://localhost:5002
- **API docs (Swagger UI):** http://localhost:5002/docs
- **OpenAPI document:** http://localhost:5002/openapi.json

### Manual Docker Commands

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

**Solution:** Stop existing process or change port in tasks.json
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
├── .vscode/
│   └── tasks.json         # VS Code build/run tasks
├── db_scripts/            # Database migration scripts
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
│   ├── models/            # SQLAlchemy models
│   ├── schemas/           # Pydantic schemas
│   └── utils/             # Utility functions
```

The server calls the factory, so nothing builds an application at import:
`uvicorn --factory app.main:create_app`.

## Development Workflow

1. Make code changes
2. Press F5 to rebuild and run in Docker
3. Test endpoints at http://localhost:5002/docs
4. Check logs in VS Code Debug Console
5. Set breakpoints for debugging

## Tests

```bash
uv run pytest
```

The tests run against a temporary SQLite file and need no database server
and no environment variables. See `tests/conftest.py` for the design rules.

## Additional Resources

- [Backend Architecture Guide](.github/copilot-instructions.md)
- [Database Migration Guide](db_scripts/DOCKER_IMPORT_GUIDE.md)
- [Stats Workflow](STATS_WORKFLOW.md)
