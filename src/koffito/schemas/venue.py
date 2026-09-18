import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VenueCreate(BaseModel):
    name: str
    address: str
    maps_url: str | None = None
    capacity: int = Field(gt=0)


class VenueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    address: str
    maps_url: str | None
    capacity: int
    is_active: bool
    created_at: datetime
