"""Venue assignment: give every matched group a café.

Groups normally inherit the event's default venue on insert; this job handles the rest. v1
picks the first active café that can seat the group (largest capacity first, unknown capacity
counts as "fits", then by name for a stable choice).

Flow:
  1. load groups with no venue whose event is upcoming
  2. load active venues (capacity, coordinates, popular_times)
  3. choose_venue(): capacity >= group size (v2: distance to the members, popular_times)
  4. PATCH the group: venue_id
  5. reservations are confirmed by an admin, not here; the event turns 'confirmed' then
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..db import Database, ServiceAuth

logger = logging.getLogger(__name__)


@dataclass
class VenueStats:
    groups_considered: int = 0
    venues_assigned: int = 0


def choose_venue(group: dict[str, Any], venues: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The first active café that seats the group: largest capacity first, then by name."""
    size = group["events"]["target_group_size"]
    fitting = [v for v in venues if v.get("capacity") is None or v["capacity"] >= size]
    if not fitting:
        logger.warning("no café seats %d people: group %s left without a venue", size, group["id"])
        return None
    fitting.sort(key=lambda v: (v.get("capacity") is None, -(v.get("capacity") or 0), v["name"]))
    return fitting[0]


async def run_venue_assignment(sb: Database, *, now: datetime | None = None) -> VenueStats:
    now = now or datetime.now(UTC)
    stats = VenueStats()
    groups = await sb.fetch(
        """
        select g.id, g.event_id, g.venue_id,
               jsonb_build_object('event_at', e.event_at, 'status', e.status,
                                  'target_group_size', e.target_group_size) as events
        from public.groups g
        join public.events e on e.id = g.event_id
        where g.venue_id is null and e.event_at > %s
        """,
        [now],
        auth=ServiceAuth(),
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
