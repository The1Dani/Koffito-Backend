from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common import StrictModel
from .reports import ReportReason, ReportStatus

EventStatus = Literal["draft", "open", "matched", "confirmed", "completed", "cancelled"]
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- events -----------------------------------------------------------------------------


class AdminEventOut(BaseModel):
    """A row of `events` (via `admin_list_events()`, so `default_venue_id` is included)."""

    id: UUID
    title: str | None
    event_at: datetime
    capacity: int
    target_group_size: int
    reveal_at: datetime
    default_venue_id: UUID | None
    status: EventStatus
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class EventCreate(StrictModel):
    event_at: datetime
    target_group_size: int = Field(default=4, ge=2, le=8)
    default_venue_id: UUID | None = None
    # true → café hidden until reveal_at (event_at - 24h); false → visible from creation
    location_hidden: bool = True
    capacity: int = Field(default=40, gt=0)
    title: str | None = Field(default=None, max_length=120)
    status: Literal["draft", "open"] = "open"

    @field_validator("event_at")
    @classmethod
    def _future(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("event_at must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("event_at must be in the future")
        return value

    def to_rpc_params(self) -> dict[str, Any]:
        return {
            "p_event_at": self.event_at.isoformat(),
            "p_target_group_size": self.target_group_size,
            "p_default_venue_id": str(self.default_venue_id) if self.default_venue_id else None,
            "p_location_hidden": self.location_hidden,
            "p_capacity": self.capacity,
            "p_title": self.title,
            "p_status": self.status,
        }


class EventUpdate(StrictModel):
    title: str | None = Field(default=None, max_length=120)
    event_at: datetime | None = None
    reveal_at: datetime | None = None
    capacity: int | None = Field(default=None, gt=0)
    target_group_size: int | None = Field(default=None, ge=2, le=8)
    default_venue_id: UUID | None = None
    status: EventStatus | None = None

    def to_patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, mode="json")


class ParticipantProfile(BaseModel):
    display_name: str
    avatar_emoji: str | None = None


class AdminParticipantOut(BaseModel):
    id: UUID
    user_id: UUID
    status: str
    group_id: UUID | None
    joined_at: datetime
    confirmed_24h_at: datetime | None
    confirmed_3h_at: datetime | None
    cancelled_at: datetime | None
    attended: bool | None
    attendance_note: str | None
    reveal_opened_at: datetime | None
    reminded_24h_at: datetime | None
    reminded_3h_at: datetime | None
    profile: ParticipantProfile | None = None


# --- venues -----------------------------------------------------------------------------


class VenueOut(BaseModel):
    id: UUID
    name: str
    description: str
    photo_url: str | None
    address: str
    website: str | None
    phone: str | None
    maps_url: str | None
    google_place_id: str | None
    latitude: float | None
    longitude: float | None
    rating: float | None
    popular_times: list[int] | None
    capacity: int | None
    is_active: bool
    created_at: datetime


class VenueCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    photo_url: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    maps_url: str | None = Field(default=None, max_length=500)
    google_place_id: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    rating: float | None = Field(default=None, ge=0, le=5)
    popular_times: list[int] | None = Field(default=None, min_length=7, max_length=7)
    capacity: int | None = Field(default=None, gt=0)
    is_active: bool | None = None

    def to_insert(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, mode="json")


class VenueUpdate(VenueCreate):
    name: str | None = Field(default=None, min_length=1, max_length=120)  # type: ignore[assignment]
    address: str | None = Field(default=None, min_length=1, max_length=200)  # type: ignore[assignment]

    def to_patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, mode="json")


# --- reports ----------------------------------------------------------------------------


class AdminReportOut(BaseModel):
    """A row of the `admin_reports` view."""

    id: UUID
    reason: ReportReason
    details: str
    status: ReportStatus
    created_at: datetime
    updated_at: datetime
    event_id: UUID | None
    reporter_id: UUID
    reported_by: str
    reported_user_id: UUID | None
    reported_user_name: str | None
    handled_by: UUID | None


class ReportStatusUpdate(StrictModel):
    status: ReportStatus


class ReportStatusOut(BaseModel):
    id: UUID
    status: ReportStatus
    handled_by: UUID | None
    updated_at: datetime
