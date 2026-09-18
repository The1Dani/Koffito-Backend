import uuid

from sqlalchemy.orm import Session

from ..models import Venue


class VenueRepository:
    """Raw DB access for Venue — no validation, no business rules."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str, address: str, maps_url: str | None, capacity: int) -> Venue:
        venue = Venue(name=name, address=address, maps_url=maps_url, capacity=capacity)
        self.db.add(venue)
        self.db.commit()
        self.db.refresh(venue)
        return venue

    def get(self, venue_id: uuid.UUID) -> Venue | None:
        return self.db.get(Venue, venue_id)

    def list_active(self) -> list[Venue]:
        return self.db.query(Venue).filter(Venue.is_active).all()
