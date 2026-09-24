"""Venue assignment: give every matched group a café.

Skeleton. Groups normally inherit the event's default venue on insert; this job handles the
rest. `choose_venue()` — the selection rule — is the TODO. Until it picks something, nothing is
written.

Intended flow:
  1. load groups with no venue whose event is upcoming
  2. load active venues (capacity, coordinates, popular_times)
  3. choose_venue(): capacity >= group size, then distance to the members, then popular_times
  4. PATCH the group: venue_id (+ avg_distance)
  5. when every group of an event has reservation_status 'confirmed' → PATCH the event to
     'confirmed' (reservations themselves are confirmed by an admin, not here)
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..supabase import ServiceAuth, SupabaseRest

logger = logging.getLogger(__name__)


@dataclass
class VenueStats:
    groups_considered: int = 0
    venues_assigned: int = 0


def choose_venue(group: dict[str, Any], venues: list[dict[str, Any]]) -> dict[str, Any] | None:
    """TODO: the selection rule. Returns nothing until it exists."""
    if venues:
        logger.warning(
            "venue assignment not implemented: group %s left without a café", group["id"]
        )
    return None


async def run_venue_assignment(sb: SupabaseRest, *, now: datetime | None = None) -> VenueStats:
    now = now or datetime.now(UTC)
    stats = VenueStats()
    groups = await sb.select(
        "groups",
        auth=ServiceAuth(),
        columns="id,event_id,venue_id,events!inner(event_at,status,target_group_size)",
        filters=[("venue_id", "is.null"), ("events.event_at", f"gt.{now.isoformat()}")],
    )
    if not groups:
        return stats
    venues = await sb.select(
        "venues",
        auth=ServiceAuth(),
        columns="id,name,capacity,latitude,longitude,popular_times",
        filters=[("is_active", "eq.true")],
    )
    for group in groups:
        stats.groups_considered += 1
        venue = choose_venue(group, venues)
        if venue is None:
            continue
        await sb.update(
            "groups",
            {"venue_id": venue["id"]},
            auth=ServiceAuth(),
            filters=[("id", f"eq.{group['id']}")],
            returning=False,
        )
        stats.venues_assigned += 1
    return stats
