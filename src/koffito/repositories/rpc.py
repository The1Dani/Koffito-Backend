"""Every SQL function the backend calls, by name, in one place."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from ..supabase import Auth, Filter, Page, SupabaseRest


class RpcRepository:
    def __init__(self, sb: SupabaseRest, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    # --- signed-in user ---------------------------------------------------------------
    async def get_me(self) -> dict[str, Any] | None:
        return await self._sb.rpc("get_me", {}, auth=self._auth)

    async def get_public_profile(self, user_id: UUID) -> dict[str, Any] | None:
        return await self._sb.rpc(
            "get_public_profile", {"p_user_id": str(user_id)}, auth=self._auth
        )

    async def set_my_languages(self, languages: Sequence[str]) -> list[str]:
        return await self._sb.rpc(
            "set_my_languages", {"p_languages": list(languages)}, auth=self._auth
        )

    async def get_my_events(self) -> list[dict[str, Any]]:
        return await self._sb.rpc("get_my_events", {}, auth=self._auth)

    async def get_my_visited_venues(self) -> list[dict[str, Any]]:
        return await self._sb.rpc("get_my_visited_venues", {}, auth=self._auth)

    # --- events -----------------------------------------------------------------------
    async def get_open_events(self) -> list[dict[str, Any]]:
        return await self._sb.rpc("get_open_events", {}, auth=self._auth)

    async def join_event(self, event_id: UUID) -> None:
        await self._sb.rpc("join_event", {"p_event_id": str(event_id)}, auth=self._auth)

    async def leave_event(self, event_id: UUID) -> None:
        await self._sb.rpc("leave_event", {"p_event_id": str(event_id)}, auth=self._auth)

    async def confirm_event(self, event_id: UUID, stage: str) -> None:
        await self._sb.rpc(
            "confirm_event", {"p_event_id": str(event_id), "p_stage": stage}, auth=self._auth
        )

    async def open_reveal(self, event_id: UUID) -> None:
        await self._sb.rpc("open_reveal", {"p_event_id": str(event_id)}, auth=self._auth)

    async def report_attendance(self, event_id: UUID, happened: bool, note: str | None) -> None:
        await self._sb.rpc(
            "report_attendance",
            {"p_event_id": str(event_id), "p_happened": happened, "p_note": note},
            auth=self._auth,
        )

    async def rate_event(self, event_id: UUID, rating: int, comment: str) -> dict[str, Any]:
        return await self._sb.rpc(
            "rate_event",
            {"p_event_id": str(event_id), "p_rating": rating, "p_comment": comment},
            auth=self._auth,
        )

    # --- admin ------------------------------------------------------------------------
    async def is_admin(self) -> bool:
        return await self._sb.rpc("is_admin", {}, auth=self._auth) is True

    async def create_event(self, params: dict[str, Any]) -> UUID:
        return UUID(await self._sb.rpc("create_event", params, auth=self._auth))

    async def admin_list_events(
        self, *, filters: Sequence[Filter] = (), order: str, limit: int, offset: int
    ) -> Page:
        return await self._sb.rpc(
            "admin_list_events",
            {},
            auth=self._auth,
            filters=filters,
            order=order,
            limit=limit,
            offset=offset,
            count=True,
        )

    async def admin_get_event(self, event_id: UUID) -> dict[str, Any]:
        return await self._sb.rpc(
            "admin_list_events",
            {},
            auth=self._auth,
            filters=[("id", f"eq.{event_id}")],
            single=True,
        )
