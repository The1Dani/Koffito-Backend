from uuid import UUID

from fastapi import APIRouter, Depends, Response

from ...schemas import AttendanceIn, ConfirmIn, OpenEventOut, RatingIn, RatingOut
from ...services import EventService
from ..deps import READ, WRITE, get_current_user, get_event_service

router = APIRouter(prefix="/events", tags=["events"], dependencies=[Depends(get_current_user)])

NO_CONTENT = {"status_code": 204, "response_class": Response, "dependencies": [Depends(WRITE)]}


@router.get("", response_model=list[OpenEventOut], dependencies=[Depends(READ)])
async def list_open_events(service: EventService = Depends(get_event_service)):
    """Upcoming events that are open for joining (`get_open_events()`)."""
    return await service.list_open()


@router.post("/{event_id}/join", **NO_CONTENT)
async def join_event(event_id: UUID, service: EventService = Depends(get_event_service)):
    """Join an open event. 409: survey_incomplete, event_not_open, time_conflict, event_full."""
    await service.join(event_id)
    return Response(status_code=204)


@router.post("/{event_id}/leave", **NO_CONTENT)
async def leave_event(event_id: UUID, service: EventService = Depends(get_event_service)):
    """Cancel participation before the event. 409: nothing_to_cancel."""
    await service.leave(event_id)
    return Response(status_code=204)


@router.post("/{event_id}/confirm", **NO_CONTENT)
async def confirm_event(
    event_id: UUID, body: ConfirmIn, service: EventService = Depends(get_event_service)
):
    """24h / 3h attendance confirmation. 409: event_not_confirmable, nothing_to_confirm."""
    await service.confirm(event_id, body)
    return Response(status_code=204)


@router.post("/{event_id}/reveal", **NO_CONTENT)
async def open_reveal(event_id: UUID, service: EventService = Depends(get_event_service)):
    """Mark the revealed café as opened by the user. 409: not_revealed_yet."""
    await service.open_reveal(event_id)
    return Response(status_code=204)


@router.post("/{event_id}/attendance", **NO_CONTENT)
async def report_attendance(
    event_id: UUID, body: AttendanceIn, service: EventService = Depends(get_event_service)
):
    """After the event: did the coffee talk happen? 409: nothing_to_confirm."""
    await service.report_attendance(event_id, body)
    return Response(status_code=204)


@router.put("/{event_id}/rating", response_model=RatingOut, dependencies=[Depends(WRITE)])
async def rate_event(
    event_id: UUID, body: RatingIn, service: EventService = Depends(get_event_service)
):
    """Create or replace the user's rating for an attended event. 409: not_attended."""
    return await service.rate(event_id, body)
