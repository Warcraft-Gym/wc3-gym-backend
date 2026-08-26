"""Vercel entry point: exposes the FastAPI ASGI app.

create_app() reads DB_URL from the environment at cold start; a placeholder is
enough to import cleanly (the engine connects lazily on first query).
"""

from app.main import create_app

app = create_app()
