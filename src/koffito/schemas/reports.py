from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common import StrictModel

ReportReason = Literal["no-show", "rude", "unsafe", "fake", "other"]
ReportStatus = Literal["open", "reviewing", "resolved"]


class ReportIn(StrictModel):
    reported_user_id: UUID | None = None
    event_id: UUID | None = None
    reason: ReportReason
    details: str = Field(min_length=10, max_length=2000)

    @field_validator("details")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("details must be at least 10 characters")
        return value


class ReportOut(BaseModel):
    id: UUID
    reason: ReportReason
    details: str
    status: ReportStatus
    event_id: UUID | None
    reported_user_id: UUID | None
    created_at: datetime
