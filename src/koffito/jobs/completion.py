"""Event completion: close coffee talks once they are over.

Stats, "cafés you've visited" and the post-event review flow only count events whose status is
`completed`, and nothing else moves an event there. This job flips every `open`, `matched` or
`confirmed` event that started more than COMPLETION_GRACE ago.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..supabase import ServiceAuth, SupabaseRest

logger = logging.getLogger(__name__)

COMPLETION_GRACE = timedelta(hours=2)
ACTIVE_STATUSES = "in.(open,matched,confirmed)"


@dataclass
class CompletionStats:
    events_completed: int = 0


async def run_completion(sb: SupabaseRest, *, now: datetime | None = None) -> CompletionStats:
    now = now or datetime.now(UTC)
    cutoff = now - COMPLETION_GRACE
    rows = await sb.update(
        "events",
        {"status": "completed"},
        auth=ServiceAuth(),
        filters=[("status", ACTIVE_STATUSES), ("event_at", f"lte.{cutoff.isoformat()}")],
        columns="id",
    )
    completed = len(rows) if isinstance(rows, list) else 0
    if completed:
        logger.info("completed %d event(s) that ended before %s", completed, cutoff.isoformat())
    return CompletionStats(events_completed=completed)
