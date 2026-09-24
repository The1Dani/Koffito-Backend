from typing import Any
from uuid import UUID

from ..core.auth import AuthenticatedUser
from ..core.errors import NotFoundError
from ..repositories import RpcRepository
from ..supabase import SupabaseRest, UserAuth


class UserService:
    def __init__(self, sb: SupabaseRest, user: AuthenticatedUser) -> None:
        self.user = user
        self._rpc = RpcRepository(sb, UserAuth(user.token))

    async def public_profile(self, user_id: UUID) -> dict[str, Any]:
        # The RPC returns null both for "no such user" and "not visible to you"; the app
        # gets the same 404 either way, on purpose.
        card = await self._rpc.get_public_profile(user_id)
        if card is None:
            raise NotFoundError("Profile not found", code="profile_not_found")
        return card
