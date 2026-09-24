"""Dependency wiring: settings, the shared Supabase client, auth and rate-limit presets."""

from fastapi import Depends, Request

from ..core.auth import AuthenticatedUser, get_current_user
from ..core.config import Settings
from ..core.errors import ForbiddenError
from ..core.ratelimit import RateLimit, rate_limited
from ..services import (
    AdminEventService,
    AdminReportService,
    AdminVenueService,
    EventService,
    MeService,
    ReportService,
    UserService,
)
from ..supabase import SupabaseRest, UserAuth

__all__ = [
    "ADMIN",
    "READ",
    "REPORT",
    "WRITE",
    "AuthenticatedUser",
    "get_admin_event_service",
    "get_admin_report_service",
    "get_admin_venue_service",
    "get_current_user",
    "get_event_service",
    "get_me_service",
    "get_report_service",
    "get_settings",
    "get_supabase",
    "get_user_service",
    "require_admin",
]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_supabase(request: Request) -> SupabaseRest:
    return request.app.state.supabase


async def require_admin(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: SupabaseRest = Depends(get_supabase),
) -> AuthenticatedUser:
    """Admin gate: asks the database (`is_admin()`, i.e. `profiles.is_admin`) with the user's
    own token. Nothing in the JWT is trusted for this."""
    if await sb.rpc("is_admin", {}, auth=UserAuth(user.token)) is not True:
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
    sb: SupabaseRest = Depends(get_supabase),
) -> MeService:
    return MeService(sb, user)


def get_event_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: SupabaseRest = Depends(get_supabase),
) -> EventService:
    return EventService(sb, user)


def get_user_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: SupabaseRest = Depends(get_supabase),
) -> UserService:
    return UserService(sb, user)


def get_report_service(
    user: AuthenticatedUser = Depends(get_current_user),
    sb: SupabaseRest = Depends(get_supabase),
) -> ReportService:
    return ReportService(sb, user)


def get_admin_event_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: SupabaseRest = Depends(get_supabase),
) -> AdminEventService:
    return AdminEventService(sb, user)


def get_admin_venue_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: SupabaseRest = Depends(get_supabase),
) -> AdminVenueService:
    return AdminVenueService(sb, user)


def get_admin_report_service(
    user: AuthenticatedUser = Depends(require_admin),
    sb: SupabaseRest = Depends(get_supabase),
) -> AdminReportService:
    return AdminReportService(sb, user)
