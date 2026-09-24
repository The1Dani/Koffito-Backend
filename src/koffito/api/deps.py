"""Dependency wiring: settings, the shared Supabase client, auth and rate-limit presets."""

from fastapi import Depends, Request

from ..core.auth import AuthenticatedUser, get_current_user
from ..core.config import Settings
from ..core.errors import ForbiddenError
from ..core.ratelimit import RateLimit, rate_limited
from ..supabase import SupabaseRest, UserAuth

__all__ = [
    "ADMIN",
    "READ",
    "REPORT",
    "WRITE",
    "AuthenticatedUser",
    "get_current_user",
    "get_settings",
    "get_supabase",
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
