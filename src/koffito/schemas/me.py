from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from .common import StrictModel

Gender = Literal["female", "male", "non_binary", "prefer_not_to_say"]
Language = Literal["ro", "ru", "en"]

MIN_AGE_YEARS = 18


class ProfileUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    avatar_emoji: str | None = Field(default=None, max_length=8)
    avatar_url: HttpUrl | None = None
    gender: Gender | None = None
    date_of_birth: date | None = None
    occupation: str | None = Field(default=None, max_length=80)
    favorite_coffee: str | None = Field(default=None, max_length=80)
    # true → onboarded now, false → back to not onboarded
    onboarded: bool | None = None

    @field_validator("display_name")
    @classmethod
    def _display_name_not_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("display_name cannot be null")
        return value.strip()

    @field_validator("date_of_birth")
    @classmethod
    def _adult(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = date.today()
        cutoff = today.replace(year=today.year - MIN_AGE_YEARS)
        if value > cutoff or value < date(1900, 1, 1):
            raise ValueError(f"must be at least {MIN_AGE_YEARS} years old")
        return value

    def to_patch(self) -> dict[str, Any]:
        """Only the fields the client sent, in the shape the `profiles` table expects."""
        values = self.model_dump(exclude_unset=True, mode="json")
        if "onboarded" in values:
            onboarded = values.pop("onboarded")
            values["onboarded_at"] = datetime.now(UTC).isoformat() if onboarded else None
        return values


class ProfileOut(BaseModel):
    id: UUID
    display_name: str
    avatar_emoji: str | None
    avatar_url: str | None
    gender: Gender | None
    date_of_birth: date | None
    occupation: str | None
    favorite_coffee: str | None
    onboarded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MeStats(BaseModel):
    coffeeTalks: int = 0
    cafesVisited: int = 0
    peopleMet: int = 0


class MeSettings(BaseModel):
    notificationsEnabled: bool = True
    remindersEnabled: bool = True


class MeOut(BaseModel):
    """`get_me()` as the database builds it (camelCase, ready for the app)."""

    id: UUID
    name: str
    emoji: str | None = None
    gender: Gender | None = None
    age: int | None = None
    languages: list[str] = []
    occupation: str | None = None
    favoriteCoffee: str | None = None
    survey: dict[str, Any] = {}
    stats: MeStats
    isAdmin: bool
    onboarded: bool
    settings: MeSettings


class LanguagesIn(StrictModel):
    languages: list[Language] = Field(max_length=3)

    @field_validator("languages")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("languages must be unique")
        return value


class LanguagesOut(BaseModel):
    languages: list[Language]


class SettingsUpdate(StrictModel):
    notifications_enabled: bool | None = None
    reminders_enabled: bool | None = None

    def to_patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class SettingsOut(BaseModel):
    notifications_enabled: bool
    reminders_enabled: bool
    updated_at: datetime


class SurveyIn(StrictModel):
    # {question id: [selected answers]} — the shape `is_valid_survey_data()` enforces in the DB.
    survey_data: dict[str, list[str]] = Field(max_length=200)
    completed: bool = True

    @field_validator("survey_data")
    @classmethod
    def _bounded(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        for question, answers in value.items():
            if len(question) > 100 or len(answers) > 50 or any(len(a) > 200 for a in answers):
                raise ValueError("survey answers are too long")
        return value


class SurveyOut(BaseModel):
    survey_data: dict[str, Any]
    completed_at: datetime | None
    completed: bool = False

    @model_validator(mode="after")
    def _derive_completed(self) -> SurveyOut:
        self.completed = self.completed_at is not None
        return self


class MyEventOut(BaseModel):
    """One row of `get_my_events()`."""

    id: UUID
    event_at: datetime
    reveal_at: datetime
    status: Literal["pending", "confirmed", "completed", "cancelled"]
    participant_status: str
    joined: bool
    blind: bool
    location_hidden: bool
    reveal_opened: bool
    max_participants: int
    cafe: dict[str, Any] | None = None
    participants: list[dict[str, Any]] | None = None
    attended: bool | None = None
    attendance_note: str | None = None
    my_rating: int | None = None
    my_comment: str | None = None


class VenueCard(BaseModel):
    """`venue_card()` as the database builds it."""

    id: UUID
    name: str
    description: str = ""
    photo: str | None = None
    address: str
    website: str | None = None
    phone: str | None = None
    mapsUrl: str | None = None
    rating: float | None = None
    popularTimes: list[int] = []
