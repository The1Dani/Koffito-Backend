import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.routes import events, me, reports, root, users
from .core.auth import JWKSCache, TokenVerifier
from .core.config import Settings, get_settings
from .core.errors import register_exception_handlers
from .core.logging import configure_logging
from .core.ratelimit import SlidingWindowLimiter
from .supabase import SupabaseRest
from .supabase.errors import register_supabase_error_handler

logger = logging.getLogger(__name__)


def _version() -> str:
    try:
        return version("koffito")
    except PackageNotFoundError:  # Docker runs the source tree without installing the package
        return "0.1.0"


def create_app(
    settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """Build the API. `transport` lets tests point the shared HTTP client at a fake Supabase."""
    settings = settings or get_settings()
    app_version = _version()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.supabase_timeout_seconds),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            transport=transport,
            headers={"User-Agent": f"koffito-backend/{app_version}"},
        )
        jwks = JWKSCache(
            http,
            settings.jwks_url,
            ttl=settings.jwks_cache_ttl_seconds,
            min_refetch=settings.jwks_min_refetch_seconds,
        )
        try:
            await jwks.refresh()
        except httpx.HTTPError as exc:
            if settings.environment == "production":
                await http.aclose()
                raise
            logger.warning("could not warm the JWKS cache (%s); retrying on first request", exc)

        service_key = settings.supabase_service_role_key
        app.state.settings = settings
        app.state.http = http
        app.state.jwks = jwks
        app.state.verifier = TokenVerifier(
            jwks,
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            leeway=settings.jwt_leeway_seconds,
        )
        app.state.supabase = SupabaseRest(
            http,
            rest_url=settings.rest_url,
            publishable_key=settings.supabase_publishable_key,
            service_key=service_key.get_secret_value() if service_key else None,
            backend_key=settings.koffito_backend_key.get_secret_value(),
        )
        app.state.limiter = SlidingWindowLimiter()

        jobs_task: asyncio.Task[None] | None = None
        if settings.jobs_enabled:
            if service_key is None:
                await http.aclose()
                raise RuntimeError("JOBS_ENABLED=true requires SUPABASE_SERVICE_ROLE_KEY")
            from .jobs.runner import run_forever

            jobs_task = asyncio.create_task(
                run_forever(app.state.supabase, interval=settings.jobs_interval_seconds),
                name="koffito-jobs",
            )
        try:
            yield
        finally:
            if jobs_task is not None:
                jobs_task.cancel()
                await asyncio.gather(jobs_task, return_exceptions=True)
            await http.aclose()

    app = FastAPI(
        title="Koffito API",
        version=app_version,
        description="Koffito backend. All data routes require a Supabase access token.",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    register_supabase_error_handler(app)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )
    if settings.enforce_https:
        # TLS terminates at the proxy; uvicorn must run with --proxy-headers for the scheme
        # check to see X-Forwarded-Proto. HTTPSRedirect is added last so it runs outermost.
        @app.middleware("http")
        async def hsts(request: Request, call_next):  # type: ignore[no-untyped-def]
            response = await call_next(request)
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
        app.add_middleware(HTTPSRedirectMiddleware)

    app.include_router(root.router)
    app.include_router(me.router)
    app.include_router(events.router)
    app.include_router(users.router)
    app.include_router(reports.router)
    return app
