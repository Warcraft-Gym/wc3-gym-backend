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

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.main import api_router
from app.core.db import init_engine
from app.core.exceptions import (
    ApiError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
    W3CThrottledError,
)

logger = logging.getLogger(__name__)


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
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        # Browsers hide custom response headers unless CORS exposes them
        expose_headers=["X-Total-Count"],
    )

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        logger.warning(exc)
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(BadRequestError)
    async def bad_request(request: Request, exc: BadRequestError) -> JSONResponse:
        logger.warning(exc)
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(ExternalServiceError)
    async def external_service(
        request: Request, exc: ExternalServiceError
    ) -> JSONResponse:
        """A service outside the app failed, so the app answers for it."""
        # A refused burst is the other side pacing the app, not an incident.
        logger.log(
            logging.WARNING if isinstance(exc, W3CThrottledError) else logging.ERROR,
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=502)

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        """The database refused the write because another row depends on
        it, so the request conflicts with the data rather than failing."""
        logger.warning("Integrity error", exc_info=exc)
        return JSONResponse({"error": "Row is still referenced"}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """The database itself failed. The message is fixed because it
        goes to the client; what the database said, including the
        statement, goes to the log."""
        logger.error("Database error", exc_info=exc)
        return JSONResponse({"error": "Database error"}, status_code=500)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        """A status and a body a route named itself."""
        return JSONResponse(exc.body, status_code=exc.status_code)

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

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """The router's own errors: unknown path, wrong method.

        Registered for Starlette's class, not FastAPI's, because the
        router raises Starlette's and FastAPI's inherits from it — this
        handler answers for both. It keeps the error envelope every
        other answer uses."""
        return JSONResponse(
            {"error": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """A bug. The body names no detail; the detail and the traceback
        go to the log."""
        logger.error("Unhandled error", exc_info=exc)
        return JSONResponse({"error": "Internal Server Error"}, status_code=500)

    app.include_router(api_router)

    logger.debug("Application built")
    return app
