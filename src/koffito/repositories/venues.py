from typing import Any
from uuid import UUID

from ..db import Auth, Database


class VenueRepository:
    def __init__(self, sb: Database, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def list(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        filters = [] if include_inactive else [("is_active", "eq.true")]
        return await self._sb.select("venues", auth=self._auth, filters=filters, order="name.asc")

    async def get(self, venue_id: UUID) -> dict[str, Any]:
        return await self._sb.select(
            "venues", auth=self._auth, filters=[("id", f"eq.{venue_id}")], single=True
        )

    async def create(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.insert("venues", values, auth=self._auth, columns="*")

    async def update(self, venue_id: UUID, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.update(
            "venues", values, auth=self._auth, filters=[("id", f"eq.{venue_id}")], columns="*"
        )
