from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...schemas import (
    AdminEventOut,
    AdminParticipantOut,
    EventCreate,
    EventStatus,
    EventUpdate,
    Page,
)
from ...services import AdminEventService
from ..deps import ADMIN, get_admin_event_service, get_current_user, require_admin

router = APIRouter(
    prefix="/admin/events",
    tags=["admin"],
    dependencies=[Depends(get_current_user), Depends(ADMIN), Depends(require_admin)],
)


@router.get("", response_model=Page[AdminEventOut])
async def list_events(
    service: AdminEventService = Depends(get_admin_event_service),
    status: EventStatus | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """All events including drafts, newest first."""
    page = await service.list(status=status, from_=from_, to=to, limit=limit, offset=offset)
    return {"items": page.items, "total": page.total, "limit": limit, "offset": offset}


@router.post("", response_model=AdminEventOut, status_code=201)
async def create_event(
    body: EventCreate, service: AdminEventService = Depends(get_admin_event_service)
):
    """Create an event via `create_event()`. 422: event_in_the_past."""
    return await service.create(body)


@router.get("/{event_id}", response_model=AdminEventOut)
async def get_event(event_id: UUID, service: AdminEventService = Depends(get_admin_event_service)):
    return await service.get(event_id)


@router.patch("/{event_id}", response_model=AdminEventOut)
async def update_event(
    event_id: UUID, body: EventUpdate, service: AdminEventService = Depends(get_admin_event_service)
):
    """Edit an event. 422: constraint_violation (reveal_at must be <= event_at, capacity > 0)."""
    return await service.update(event_id, body)


@router.get("/{event_id}/participants", response_model=list[AdminParticipantOut])
async def list_participants(
    event_id: UUID, service: AdminEventService = Depends(get_admin_event_service)
):
    return await service.participants(event_id)
