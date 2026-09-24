from typing import Any

from ..core.auth import AuthenticatedUser
from ..repositories import ReportRepository
from ..schemas import ReportIn
from ..supabase import SupabaseRest, UserAuth


class ReportService:
    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        self._reports = ReportRepository(sb, UserAuth(user.token))

    async def create(self, body: ReportIn) -> dict[str, Any]:
        values = body.model_dump(mode="json")
        values["reporter_id"] = str(self.user.id)  # from the token, never from the body
        rows = await self._reports.create(values)
        return rows[0]
