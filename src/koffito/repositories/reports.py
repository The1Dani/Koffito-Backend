from typing import Any
from uuid import UUID

from ..db import Auth, Database, Filter, Page

REPORT_COLUMNS = "id,reason,details,status,event_id,reported_user_id,created_at"


class ReportRepository:
    def __init__(self, sb: Database, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def create(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.insert("reports", values, auth=self._auth, columns=REPORT_COLUMNS)

    async def admin_list(self, *, filters: list[Filter], limit: int, offset: int) -> Page:
        return await self._sb.select(
            "admin_reports",
            auth=self._auth,
            filters=filters,
            order="created_at.desc",
            limit=limit,
            offset=offset,
            count=True,
        )

    async def set_status(
        self, report_id: UUID, status: str, handled_by: UUID
    ) -> list[dict[str, Any]]:
        return await self._sb.update(
            "reports",
            {"status": status, "handled_by": str(handled_by)},
            auth=self._auth,
            filters=[("id", f"eq.{report_id}")],
            columns="id,status,handled_by,updated_at",
        )
