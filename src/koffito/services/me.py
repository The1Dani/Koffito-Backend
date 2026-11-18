from datetime import UTC, datetime
from typing import Any

from ..core.auth import AuthenticatedUser
from ..core.errors import NotFoundError, UnprocessableError
from ..db import Database, DatabaseError, UserAuth
from ..repositories import ProfileRepository, RpcRepository
from ..schemas import LanguagesIn, ProfileUpdate, SettingsUpdate, SurveyIn


class MeService:
    """Everything about the signed-in user. Every call runs with the user's own token."""

    def __init__(self, sb: Database, user: AuthenticatedUser) -> None:
        self.user = user
        auth = UserAuth(user.id)
        self._rpc = RpcRepository(sb, auth)
        self._profiles = ProfileRepository(sb, auth)

    async def get_me(self) -> dict[str, Any]:
        me = await self._rpc.get_me()
        if me is None:
            raise NotFoundError("Profile not found", code="profile_not_found")
        return me

    async def update_profile(self, patch: ProfileUpdate) -> dict[str, Any]:
        values = patch.to_patch()
        if not values:
            raise UnprocessableError("Nothing to update", code="empty_update")
        rows = await self._profiles.update_profile(self.user.id, values)
        if not rows:
            raise NotFoundError("Profile not found", code="profile_not_found")
        return rows[0]

    async def set_languages(self, body: LanguagesIn) -> list[str]:
        return await self._rpc.set_my_languages(body.languages)

    async def update_settings(self, patch: SettingsUpdate) -> dict[str, Any]:
        values = patch.to_patch()
        if not values:
            raise UnprocessableError("Nothing to update", code="empty_update")
        rows = await self._profiles.update_settings(self.user.id, values)
        if not rows:
            raise NotFoundError("Settings not found", code="settings_not_found")
        return rows[0]

    async def get_survey(self) -> dict[str, Any]:
        try:
            return await self._profiles.get_survey(self.user.id)
        except DatabaseError as exc:
            if exc.code == "not_found":
                raise NotFoundError("No survey yet", code="survey_not_found") from exc
            raise

    async def put_survey(self, body: SurveyIn) -> dict[str, Any]:
        completed_at = datetime.now(UTC).isoformat() if body.completed else None
        rows = await self._profiles.upsert_survey(self.user.id, body.survey_data, completed_at)
        return rows[0]

    async def my_events(self) -> list[dict[str, Any]]:
        return await self._rpc.get_my_events()

    async def visited_venues(self) -> list[dict[str, Any]]:
        return await self._rpc.get_my_visited_venues()
