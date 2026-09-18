import uuid

from fastapi import APIRouter, Depends, HTTPException

from ...schemas import VenueCreate, VenueOut
from ...services import VenueNotFound, VenueService
from ..deps import get_venue_service

router = APIRouter(prefix="/venues", tags=["venues"])


@router.post("", response_model=VenueOut)
def create_venue(venue: VenueCreate, service: VenueService = Depends(get_venue_service)):
    return service.create_venue(venue.name, venue.address, venue.maps_url, venue.capacity)


@router.get("", response_model=list[VenueOut])
def list_venues(service: VenueService = Depends(get_venue_service)):
    return service.list_venues()


@router.get("/{venue_id}", response_model=VenueOut)
def read_venue(venue_id: uuid.UUID, service: VenueService = Depends(get_venue_service)):
    try:
        return service.get_venue(venue_id)
    except VenueNotFound:
        raise HTTPException(status_code=404, detail="Venue not found")
