from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .common import StrictModel


class OpenEventOut(BaseModel):
    """One row of `get_open_events()`. `max_participants` is the target group size."""

    id: UUID
    event_at: datetime
    max_participants: int
    spots_left: int
    joined: bool


class ConfirmIn(StrictModel):
    stage: Literal["24h", "3h"]


class AttendanceIn(StrictModel):
    happened: bool
    note: str | None = Field(default=None, max_length=500)


class RatingIn(StrictModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class RatingOut(BaseModel):
    event_id: UUID
    rating: int
    comment: str
    created_at: datetime
    updated_at: datetime
