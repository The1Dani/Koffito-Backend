from fastapi import Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import VenueService


def get_venue_service(db: Session = Depends(get_db)) -> VenueService:
    return VenueService(db)
