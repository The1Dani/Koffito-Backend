from datetime import datetime
from typing import Any
from uuid import UUID

from ..core.auth import AuthenticatedUser
from ..core.errors import NotFoundError, UnprocessableError
from ..repositories import EventRepository, ReportRepository, RpcRepository, VenueRepository
from ..schemas import EventCreate, EventUpdate, ReportStatusUpdate, VenueCreate, VenueUpdate
from ..supabase import Filter, Page, SupabaseError, SupabaseRest, UserAuth


def _not_found_on_pgrst116(exc: SupabaseError, code: str, message: str) -> None:
    if exc.code == "PGRST116":
        raise NotFoundError(message, code=code) from exc
    raise exc


class AdminEventService:
    """Event administration. Runs with the admin's own token: RLS `is_admin()` policies apply."""

    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        auth = UserAuth(user.token)
        self._rpc = RpcRepository(sb, auth)
        self._events = EventRepository(sb, auth)

    async def list(
        self,
        *,
        status: str | None,
        from_: datetime | None,
        to: datetime | None,
        limit: int,
        offset: int,
    ) -> Page:
        filters: list[Filter] = []
        if status:
            filters.append(("status", f"eq.{status}"))
        if from_:
            filters.append(("event_at", f"gte.{from_.isoformat()}"))
        if to:
            filters.append(("event_at", f"lte.{to.isoformat()}"))
        return await self._rpc.admin_list_events(
            filters=filters, order="event_at.desc", limit=limit, offset=offset
        )

    async def get(self, event_id: UUID) -> dict[str, Any]:
        try:
            return await self._rpc.admin_get_event(event_id)
        except SupabaseError as exc:
            _not_found_on_pgrst116(exc, "event_not_found", "Event not found")
            raise

    async def create(self, body: EventCreate) -> dict[str, Any]:
        event_id = await self._rpc.create_event(body.to_rpc_params())
        return await self.get(event_id)

    async def update(self, event_id: UUID, body: EventUpdate) -> dict[str, Any]:
        values = body.to_patch()
        if not values:
            raise UnprocessableError("Nothing to update", code="empty_update")
        rows = await self._events.update(event_id, values)
        if not rows:
            raise NotFoundError("Event not found", code="event_not_found")
        return await self.get(event_id)

    async def participants(self, event_id: UUID) -> list[dict[str, Any]]:
        return await self._events.participants(event_id)


class AdminVenueService:
    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        self._venues = VenueRepository(sb, UserAuth(user.token))

    async def list(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        return await self._venues.list(include_inactive=include_inactive)

    async def get(self, venue_id: UUID) -> dict[str, Any]:
        try:
            return await self._venues.get(venue_id)
        except SupabaseError as exc:
            _not_found_on_pgrst116(exc, "venue_not_found", "Venue not found")
            raise

    async def create(self, body: VenueCreate) -> dict[str, Any]:
        rows = await self._venues.create(body.to_insert())
        return rows[0]

    async def update(self, venue_id: UUID, body: VenueUpdate) -> dict[str, Any]:
        values = body.to_patch()
        if not values:
            raise UnprocessableError("Nothing to update", code="empty_update")
        return await self._update(venue_id, values)

    async def deactivate(self, venue_id: UUID) -> None:
        # groups.venue_id has no cascade, so venues are never hard-deleted.
        await self._update(venue_id, {"is_active": False})

    async def _update(self, venue_id: UUID, values: dict[str, Any]) -> dict[str, Any]:
        rows = await self._venues.update(venue_id, values)
        if not rows:
            raise NotFoundError("Venue not found", code="venue_not_found")
        return rows[0]


class AdminReportService:
    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        self._reports = ReportRepository(sb, UserAuth(user.token))

    async def list(self, *, status: str | None, limit: int, offset: int) -> Page:
        filters: list[Filter] = [("status", f"eq.{status}")] if status else []
        return await self._reports.admin_list(filters=filters, limit=limit, offset=offset)

    async def set_status(self, report_id: UUID, body: ReportStatusUpdate) -> dict[str, Any]:
        rows = await self._reports.set_status(report_id, body.status, self.user.id)
        if not rows:
            raise NotFoundError("Report not found", code="report_not_found")
        return rows[0]
