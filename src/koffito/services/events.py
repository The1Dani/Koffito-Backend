from typing import Any
from uuid import UUID

from ..core.auth import AuthenticatedUser
from ..repositories import RpcRepository
from ..schemas import AttendanceIn, ConfirmIn, RatingIn
from ..supabase import SupabaseRest, UserAuth


class EventService:
    """Event participation for the signed-in user; every rule lives in the SQL RPCs."""

    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        self._rpc = RpcRepository(sb, UserAuth(user.token))

    async def list_open(self) -> list[dict[str, Any]]:
        return await self._rpc.get_open_events()

    async def join(self, event_id: UUID) -> None:
        await self._rpc.join_event(event_id)

    async def leave(self, event_id: UUID) -> None:
        await self._rpc.leave_event(event_id)

    async def confirm(self, event_id: UUID, body: ConfirmIn) -> None:
        await self._rpc.confirm_event(event_id, body.stage)

    async def open_reveal(self, event_id: UUID) -> None:
        await self._rpc.open_reveal(event_id)

    async def report_attendance(self, event_id: UUID, body: AttendanceIn) -> None:
        await self._rpc.report_attendance(event_id, body.happened, body.note)

    async def rate(self, event_id: UUID, body: RatingIn) -> dict[str, Any]:
        return await self._rpc.rate_event(event_id, body.rating, body.comment)
