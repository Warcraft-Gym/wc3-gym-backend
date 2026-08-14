"""The application factory.

Importing this module defines create_app and imports the layers below it.
It opens no database connection and creates no tables. Everything that
touches the database happens inside create_app, so a test or a script can
import any app module without a reachable database.

The server calls the factory itself, as
`uvicorn --factory app.main:create_app`, so no application is built at
import.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import AuthError
from app.api.main import api_router
from app.core.db import init_engine
from app.exceptions import DBException, NotFoundException

logger = logging.getLogger(__name__)

# Production has one CPU core and served one request at a time before the
# port (one gunicorn sync worker). The routes are sync functions, so this
# caps the thread pool they run in to keep that behaviour.
MAX_CONCURRENT_REQUESTS = 1


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = MAX_CONCURRENT_REQUESTS
    yield


def create_app(db_url: str | None = None) -> FastAPI:
    """Build the application: engine, routers.

    Reads the environment when the caller passes no db_url. The tables come
    from `alembic upgrade head`, which runs before the server starts.
    """
    load_dotenv()
    # A wrong LOG_LEVEL must not stop the application.
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )

    init_engine(db_url)

    app = FastAPI(
        title="GNL Backend API",
        description="API for Gym Newbie League Backend Data",
        version="1.0.0",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFoundException)
    async def not_found(request: Request, exc: NotFoundException) -> JSONResponse:
        logger.error(exc)
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(DBException)
    async def db_error(request: Request, exc: DBException) -> JSONResponse:
        logger.error(exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse({"msg": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """A body the route model rejects.

        The answer keeps the error field every other failure uses, because
        the frontend reads that field to decide a request failed. The list
        of fields goes into the message.
        """
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'][1:])}: {error['msg']}"
            for error in exc.errors()
        )
        logger.error("Invalid request: %s", problems)
        return JSONResponse({"error": problems}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error(exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    app.include_router(api_router)

    logger.debug("Application built")
    return app
