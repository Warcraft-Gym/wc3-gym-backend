FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

EXPOSE 5002

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Use the image's Python instead of downloading a managed one
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install dependencies before the code so this layer caches across code changes.
# The project itself installs in the second sync, after the source is copied.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . /app
RUN uv sync --frozen --no-dev

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

# The project environment on PATH lets gunicorn run without uv at runtime
ENV PATH="/app/.venv/bin:$PATH"

# During debugging, this entry point will be overridden. uvicorn has no
# worker timeout, so the long import/export requests need no --timeout.
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "5002"]
