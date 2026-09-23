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
from time import perf_counter

from anyio import to_thread
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from vercel.headers import set_headers

from app.api.main import api_router
from app.core.db import Cost, init_engine, start_request_cost
from app.core.exceptions import (
    ApiError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
    W3CThrottledError,
)
from app.services import egress

logger = logging.getLogger(__name__)

# The ledger's own read route stays out of the ledger
UNRECORDED_ROUTES = {"/jobs/egress"}


class VercelHeadersMiddleware:
    """Hand each request's headers to the vercel SDK. On Vercel the OIDC token the blob store
    accepts arrives as the x-vercel-oidc-token header, and the SDK's token lookup reads it from
    this context, so the blob calls deep in the services and the after-commit hooks need no argument."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            set_headers(Headers(scope=scope))
        await self.app(scope, receive, send)


class EgressMiddleware:
    """Count what each request asks of the database.

    The counts go out in three response headers and one log line, and into
    the daily egress ledger. A 404 or a 405 is logged but not recorded, so a
    scanner cannot grow the ledger with made-up paths or methods. The headers carry the
    counts at the start of the response; a streamed body is not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cost = start_request_cost()
        started = perf_counter()
        # A request that raises past the handlers never starts a response: a 500
        answer = {"status": 500, "bytes": 0}

        async def send_with_cost(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                answer["status"] = message["status"]
                answer["bytes"] = int(headers.get("content-length", 0))
                headers["X-DB-Statements"] = str(cost.statements)
                headers["X-DB-Rows"] = str(cost.rows)
                headers["X-Response-Bytes"] = str(answer["bytes"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_cost)
        finally:
            # Read before the upsert, so the ledger write is not part of the request
            spent = Cost(cost.statements, cost.rows)
            route = scope.get("route")
            template = getattr(route, "path", None) or scope["path"]
            logger.info(
                "egress route=%s method=%s status=%d statements=%d rows=%d bytes=%d ms=%d",
                template,
                scope["method"],
                answer["status"],
                spent.statements,
                spent.rows,
                answer["bytes"],
                (perf_counter() - started) * 1000,
            )
            if (
                route is not None
                and answer["status"] not in (404, 405)
                and template not in UNRECORDED_ROUTES
            ):
                await to_thread.run_sync(
                    record_egress, template, scope["method"], spent, answer["bytes"]
                )


def record_egress(route: str, method: str, cost: Cost, size: int) -> None:
    """Add the request to the ledger; a failed write is logged, never raised."""
    try:
        egress.record(route, method, cost, size)
    except Exception:
        logger.warning(
            "egress ledger write failed for %s %s", method, route, exc_info=True
        )


def create_app(db_url: str | None = None) -> FastAPI:
    """Build the application: engine, routers.

    Reads the process environment when the caller passes no db_url; no .env
    file is read here, the entrypoint or the just recipe loads one. The tables come
    from `alembic upgrade head`, which runs before the server starts.
    """
    # A wrong LOG_LEVEL must not stop the application.
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    )

    init_engine(db_url)

    app = FastAPI(
        title="GNL Backend API",
        description="API for Gym Newbie League Backend Data",
        version="1.1.0",
    )
    app.add_middleware(EgressMiddleware)
    app.add_middleware(VercelHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        # Browsers hide custom response headers unless CORS exposes them
        expose_headers=[
            "X-Total-Count",
            "X-DB-Statements",
            "X-DB-Rows",
            "X-Response-Bytes",
        ],
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
        """The database refused the write because it conflicts with a row it
        already holds. A natural key that repeats and a parent another row
        still points at are different conflicts, so the client is told which.
        Postgres names the first 23505, SQLite says it in words."""
        logger.warning("Integrity error", exc_info=exc)
        repeats = getattr(exc.orig, "sqlstate", "") == "23505" or (
            "UNIQUE constraint failed" in str(exc.orig)
        )
        message = "Row already exists" if repeats else "Row is still referenced"
        return JSONResponse({"error": message}, status_code=409)

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
