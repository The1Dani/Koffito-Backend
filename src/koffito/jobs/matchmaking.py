"""Matchmaking: split an open event's participants into groups of `target_group_size`.

Skeleton. The reads and the intended writes are in place; `plan_groups()` — the actual
grouping algorithm — is the TODO. Until it returns groups, this job never writes.

Intended flow, per open event starting within MATCH_LEAD:
  1. load `joined` participants with their survey embedding, languages, gender, age
  2. plan_groups(): cluster by survey-embedding similarity (pgvector cosine; consider a
     server-side `match_event(p_event_id)` SQL function so vectors never leave Postgres),
     require at least one shared language, respect target_group_size (last group may be
     smaller; 1-person groups are re-merged)
  3. insert one `groups` row per group (venue inherited from the event by trigger)
  4. PATCH the participants: group_id + status 'matched'
  5. PATCH the event: status 'matched'
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..supabase import ServiceAuth, SupabaseRest

logger = logging.getLogger(__name__)

MATCH_LEAD = timedelta(hours=26)  # a little before the default reveal_at (event_at - 24h)
PARTICIPANT_COLUMNS = (
    "id,user_id,"
    "profiles!inner(gender,date_of_birth,surveys(embedding,embedding_version),"
    "profile_languages(language))"
)


@dataclass
class MatchmakingStats:
    events_considered: int = 0
    groups_created: int = 0
    participants_matched: int = 0


def plan_groups(participants: list[dict[str, Any]], target_size: int) -> list[list[dict[str, Any]]]:
    """TODO: the grouping algorithm. Returns no groups until it exists."""
    if participants:
        logger.warning(
            "matchmaking algorithm not implemented: %d participants left unmatched",
            len(participants),
        )
    return []


async def run_matchmaking(sb: SupabaseRest, *, now: datetime | None = None) -> MatchmakingStats:
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
