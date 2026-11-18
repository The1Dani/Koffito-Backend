import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.routes import (
    admin_events,
    admin_reports,
    admin_venues,
    auth,
    events,
    me,
    reports,
    root,
    users,
)
from .auth.mailer import Mailer
from .auth.service import AuthService
from .core.auth import TokenVerifier
from .core.config import Settings, get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging
from .core.ratelimit import SlidingWindowLimiter
from .db import Database
from .db.errors import register_database_error_handler

logger = logging.getLogger(__name__)


def _version() -> str:
    try:
        return version("koffito")
    except PackageNotFoundError:  # Docker runs the source tree without installing the package
        return "0.1.0"


def create_app(settings: Settings | None = None, *, db: Database | None = None) -> FastAPI:
    """Build the API. Tests may pass their own `db` (already pointed at a test database)."""
    settings = settings or get_settings()
    app_version = _version()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        database = db or Database(
            settings.database_url.get_secret_value(), max_size=settings.database_pool_size
        )
        await database.open()

        verifier = TokenVerifier(
            settings.auth_jwt_secret.get_secret_value(),
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            ttl_seconds=settings.access_token_ttl_minutes * 60,
            leeway=settings.jwt_leeway_seconds,
        )
        mailer = Mailer(settings)
        app.state.settings = settings
        app.state.db = database
        app.state.verifier = verifier
        app.state.mailer = mailer
        app.state.auth = AuthService(database, settings, verifier, mailer)
        app.state.limiter = SlidingWindowLimiter()

        jobs_task: asyncio.Task[None] | None = None
        if settings.jobs_enabled:
            from .jobs.runner import run_forever

            jobs_task = asyncio.create_task(
                run_forever(database, interval=settings.jobs_interval_seconds),
                name="koffito-jobs",
            )
        try:
            yield
        finally:
            if jobs_task is not None:
                jobs_task.cancel()
                await asyncio.gather(jobs_task, return_exceptions=True)
            if db is None:
                await database.close()

    app = FastAPI(
        title="Koffito API",
        version=app_version,
        description="Koffito backend. Data routes require an access token from /auth/login.",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    register_database_error_handler(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        if settings.enforce_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,  # the refresh cookie
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )
    if settings.enforce_https:
        # TLS terminates at the proxy; uvicorn must run with --proxy-headers for the scheme
        # check to see X-Forwarded-Proto. HTTPSRedirect is added last so it runs outermost.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
        app.add_middleware(HTTPSRedirectMiddleware)

    app.include_router(root.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(events.router)
    app.include_router(users.router)
    app.include_router(reports.router)
    app.include_router(admin_events.router)
    app.include_router(admin_venues.router)
    app.include_router(admin_reports.router)
    return app
