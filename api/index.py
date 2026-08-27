"""Vercel entry point: exposes the FastAPI ASGI app.

create_app() reads DB_URL from the environment at cold start; a placeholder is
enough to import cleanly (the engine connects lazily on first query).
"""

import os

from api.preview_db import preview_db_name, with_database
from app.main import create_app

if name := preview_db_name():
    os.environ["DB_URL"] = with_database(os.environ["DB_URL"], name)

app = create_app()
