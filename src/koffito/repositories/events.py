from typing import Any
from uuid import UUID

from ..db import Auth, Database


class EventRepository:
    """Direct table access to events/participants. Admin-only: callers sit behind require_admin."""

    def __init__(self, sb: Database, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def update(self, event_id: UUID, values: dict[str, Any]) -> list[dict[str, Any]]:
        # Only `id` comes back; the caller re-reads the row through admin_list_events().
        return await self._sb.update(
            "events", values, auth=self._auth, filters=[("id", f"eq.{event_id}")], columns="id"
        )

    async def participants(self, event_id: UUID) -> list[dict[str, Any]]:
        return await self._sb.fetch(
            """
            select ep.id, ep.user_id, ep.status, ep.group_id, ep.joined_at, ep.confirmed_24h_at,
                   ep.confirmed_3h_at, ep.cancelled_at, ep.attended, ep.attendance_note,
                   ep.reveal_opened_at, ep.reminded_24h_at, ep.reminded_3h_at,
                   jsonb_build_object('display_name', p.display_name,
                                      'avatar_emoji', p.avatar_emoji) as profile
            from public.event_participants ep
            join public.profiles p on p.id = ep.user_id
            where ep.event_id = %s
            order by ep.joined_at asc
            """,
            [event_id],
            auth=self._auth,
        )
