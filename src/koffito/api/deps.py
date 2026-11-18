"""Dependency wiring: settings, the shared database, auth and rate-limit presets."""

from fastapi import Depends, Request

from ..auth.service import AuthService
from ..core.auth import AuthenticatedUser, get_current_user
from ..core.config import Settings
from ..core.errors import ForbiddenError
from ..core.ratelimit import RateLimit, rate_limited
from ..db import Database, UserAuth
from ..services import (
    AdminEventService,
    AdminReportService,
    AdminVenueService,
    EventService,
    MeService,
    ReportService,
    UserService,
)

__all__ = [
    "ADMIN",
    "READ",
    "REPORT",
    "WRITE",
    "AuthenticatedUser",
    "get_admin_event_service",
    "get_admin_report_service",
    "get_auth_service",
    "get_admin_venue_service",
    "get_current_user",
    "get_event_service",
    "get_me_service",
    "get_report_service",
    "get_settings",
    "get_db",
    "get_user_service",
    "require_admin",
]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth


async def require_admin(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: Database = Depends(get_db),
) -> AuthenticatedUser:
    """Admin gate: asks the database (`is_admin()`, i.e. `profiles.is_admin`) as this user.
    Nothing in the token is trusted for this."""
    if await sb.rpc("is_admin", {}, auth=UserAuth(user.id)) is not True:
        raise ForbiddenError("Admins only", code="admin_required")
    return user


READ = rate_limited(
    lambda s: RateLimit(s.rate_limit_read_limit, s.rate_limit_read_window_seconds, "read")
)
WRITE = rate_limited(
    lambda s: RateLimit(s.rate_limit_write_limit, s.rate_limit_write_window_seconds, "write")
)
REPORT = rate_limited(
    lambda s: RateLimit(s.rate_limit_report_limit, s.rate_limit_report_window_seconds, "report")
)
ADMIN = rate_limited(
    lambda s: RateLimit(s.rate_limit_admin_limit, s.rate_limit_admin_window_seconds, "admin")
)


def get_me_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: Database = Depends(get_db),
) -> MeService:
    return MeService(sb, user)


def get_event_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: Database = Depends(get_db),
) -> EventService:
    return EventService(sb, user)


def get_user_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: Database = Depends(get_db),
) -> UserService:
    return UserService(sb, user)


def get_report_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: Database = Depends(get_db),
) -> ReportService:
    return ReportService(sb, user)


def get_admin_event_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: Database = Depends(get_db),
) -> AdminEventService:
    return AdminEventService(sb, user)


def get_admin_venue_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: Database = Depends(get_db),
) -> AdminVenueService:
    return AdminVenueService(sb, user)


def get_admin_report_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: Database = Depends(get_db),
) -> AdminReportService:
    return AdminReportService(sb, user)
