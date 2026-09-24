from typing import Any

from ..supabase import Auth, SupabaseRest

REPORT_COLUMNS = "id,reason,details,status,event_id,reported_user_id,created_at"


class ReportRepository:
    def __init__(self, sb: SupabaseRest, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def create(self, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.insert("reports", values, auth=self._auth, columns=REPORT_COLUMNS)
