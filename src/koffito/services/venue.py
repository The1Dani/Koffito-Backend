import uuid

from sqlalchemy.orm import Session

from ..models import Venue
from ..repositories import VenueRepository


class VenueNotFound(Exception):
    def __init__(self, venue_id: uuid.UUID):
        self.venue_id = venue_id


class VenueService:
    """Business rules for venues. Routers call this, never the repository directly."""

    def __init__(self, db: Session):
        self.repo = VenueRepository(db)

    def create_venue(self, name: str, address: str, maps_url: str | None, capacity: int) -> Venue:
        return self.repo.create(name, address, maps_url, capacity)

    def get_venue(self, venue_id: uuid.UUID) -> Venue:
        venue = self.repo.get(venue_id)
        if venue is None:
            raise VenueNotFound(venue_id)
        return venue

    def list_venues(self) -> list[Venue]:
        return self.repo.list_active()
