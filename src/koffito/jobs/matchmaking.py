"""Matchmaking: split an open event's participants into groups of `target_group_size`.

v1 groups people in join order: the list of `joined` participants is chunked into groups of the
target size; a trailing group of one is merged into the previous group; a lone participant with
nobody to group with stays `joined` (and the event stays `open`) until someone else joins.

Per open event starting within MATCH_LEAD:
  1. load `joined` participants, oldest join first
  2. plan_groups()
  3. insert one `groups` row per group (venue inherited from the event by trigger)
  4. PATCH the participants: group_id + status 'matched'
  5. PATCH the event: status 'matched'

v2 (not here yet): cluster by survey-embedding similarity (pgvector cosine; consider a
server-side `match_event(p_event_id)` SQL function so vectors never leave Postgres) and require
at least one shared language.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..db import Database, ServiceAuth

logger = logging.getLogger(__name__)

MATCH_LEAD = timedelta(hours=26)  # a little before the default reveal_at (event_at - 24h)
PARTICIPANT_COLUMNS = "id,user_id,joined_at"


@dataclass
class MatchmakingStats:
    events_considered: int = 0
    groups_created: int = 0
    participants_matched: int = 0


def plan_groups(participants: list[dict[str, Any]], target_size: int) -> list[list[dict[str, Any]]]:
    """Chunk the participants (already in join order) into groups of `target_size`.

    A trailing group of one is merged into the previous group rather than left alone; a single
    participant with nobody else gets no group at all.
    """
    size = max(target_size, 2)
    groups = [participants[i : i + size] for i in range(0, len(participants), size)]
    if len(groups) >= 2 and len(groups[-1]) == 1:
        groups[-2].extend(groups.pop())
    if groups and len(groups[-1]) == 1:
        logger.info("matchmaking: one participant left unmatched (nobody to group with)")
        return []
    return groups


async def run_matchmaking(sb: Database, *, now: datetime | None = None) -> MatchmakingStats:
    now = now or datetime.now(UTC)
    stats = MatchmakingStats()
    events = await sb.select(
        "events",
        auth=ServiceAuth(),
        columns="id,event_at,target_group_size,capacity,default_venue_id",
        filters=[
            ("status", "eq.open"),
            ("event_at", f"gt.{now.isoformat()}"),
            ("event_at", f"lte.{(now + MATCH_LEAD).isoformat()}"),
        ],
    )
    for event in events:
        stats.events_considered += 1
        participants = await sb.select(
            "event_participants",
            auth=ServiceAuth(),
            columns=PARTICIPANT_COLUMNS,
            filters=[("event_id", f"eq.{event['id']}"), ("status", "eq.joined")],
            order="joined_at.asc",
        )
        groups = plan_groups(participants, event["target_group_size"])
        for members in groups:
            created = await sb.insert("groups", {"event_id": event["id"]}, auth=ServiceAuth())
            group_id = created[0]["id"]
            ids = ",".join(m["id"] for m in members)
            await sb.update(
                "event_participants",
                {"group_id": group_id, "status": "matched"},
                auth=ServiceAuth(),
                filters=[("id", f"in.({ids})")],
                returning=False,
            )
            stats.groups_created += 1
            stats.participants_matched += len(members)
        if groups:
            await sb.update(
                "events",
                {"status": "matched"},
                auth=ServiceAuth(),
                filters=[("id", f"eq.{event['id']}")],
                returning=False,
            )
    return stats
