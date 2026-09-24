from typing import Any
from uuid import UUID

from ..supabase import Auth, SupabaseRest

PROFILE_COLUMNS = (
    "id,display_name,avatar_emoji,avatar_url,gender,date_of_birth,occupation,"
    "favorite_coffee,onboarded_at,created_at,updated_at"
)
SETTINGS_COLUMNS = "notifications_enabled,reminders_enabled,updated_at"
SURVEY_COLUMNS = "survey_data,completed_at,updated_at"


class ProfileRepository:
    """Direct table access for the signed-in user's own rows (RLS keeps it to their rows)."""

    def __init__(self, sb: SupabaseRest, auth: Auth) -> None:
        self._sb = sb
        self._auth = auth

    async def update_profile(self, user_id: UUID, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.update(
            "profiles",
            values,
            auth=self._auth,
            filters=[("id", f"eq.{user_id}")],
            columns=PROFILE_COLUMNS,
        )

    async def update_settings(self, user_id: UUID, values: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._sb.update(
            "user_settings",
            values,
            auth=self._auth,
            filters=[("user_id", f"eq.{user_id}")],
            columns=SETTINGS_COLUMNS,
        )

    async def get_survey(self, user_id: UUID) -> dict[str, Any]:
        return await self._sb.select(
            "surveys",
            auth=self._auth,
            columns=SURVEY_COLUMNS,
            filters=[("user_id", f"eq.{user_id}")],
            single=True,
        )

    async def upsert_survey(
        self, user_id: UUID, survey_data: dict[str, Any], completed_at: str | None
    ) -> list[dict[str, Any]]:
        return await self._sb.insert(
            "surveys",
            {"user_id": str(user_id), "survey_data": survey_data, "completed_at": completed_at},
            auth=self._auth,
            columns=SURVEY_COLUMNS,
            upsert_on="user_id",
        )
