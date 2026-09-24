from uuid import UUID

from fastapi import APIRouter, Depends, Response

from ...schemas import VenueCreate, VenueOut, VenueUpdate
from ...services import AdminVenueService
from ..deps import ADMIN, get_admin_venue_service, require_admin

router = APIRouter(
    prefix="/admin/venues", tags=["admin"], dependencies=[Depends(require_admin), Depends(ADMIN)]
)


@router.get("", response_model=list[VenueOut])
async def list_venues(
    include_inactive: bool = False,
    service: AdminVenueService = Depends(get_admin_venue_service),
):
    return await service.list(include_inactive=include_inactive)


@router.post("", response_model=VenueOut, status_code=201)
async def create_venue(
    body: VenueCreate, service: AdminVenueService = Depends(get_admin_venue_service)
):
    return await service.create(body)


@router.get("/{venue_id}", response_model=VenueOut)
async def get_venue(venue_id: UUID, service: AdminVenueService = Depends(get_admin_venue_service)):
    return await service.get(venue_id)


@router.patch("/{venue_id}", response_model=VenueOut)
async def update_venue(
    venue_id: UUID, body: VenueUpdate, service: AdminVenueService = Depends(get_admin_venue_service)
):
    return await service.update(venue_id, body)


@router.delete("/{venue_id}", status_code=204, response_class=Response)
async def deactivate_venue(
    venue_id: UUID, service: AdminVenueService = Depends(get_admin_venue_service)
):
    """Soft delete: sets `is_active=false` (venues referenced by groups can't be removed)."""
    await service.deactivate(venue_id)
    return Response(status_code=204)
