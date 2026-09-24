from typing import Any
from uuid import UUID

from ..supabase import Auth, SupabaseRest

PARTICIPANT_COLUMNS = (
    "id,user_id,status,group_id,joined_at,confirmed_24h_at,confirmed_3h_at,cancelled_at,"
    "attended,attendance_note,reveal_opened_at,reminded_24h_at,reminded_3h_at,"
    "profile:profiles(display_name,avatar_emoji)"
)


class EventRepository:
    """Direct table access to events/participants (admin RLS decides what is visible)."""

    def __init__(self, sb: SupabaseRest, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def update(self, event_id: UUID, values: dict[str, Any]) -> list[dict[str, Any]]:
        # `authenticated` cannot read default_venue_id, so only `id` comes back; the caller
        # re-reads the row through admin_list_events().
        return await self._sb.update(
            "events", values, auth=self._auth, filters=[("id", f"eq.{event_id}")], columns="id"
        )

    async def participants(self, event_id: UUID) -> list[dict[str, Any]]:
        return await self._sb.select(
            "event_participants",
            auth=self._auth,
            columns=PARTICIPANT_COLUMNS,
            filters=[("event_id", f"eq.{event_id}")],
            order="joined_at.asc",
        )
