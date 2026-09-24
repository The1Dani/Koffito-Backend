"""24h / 3h confirmation reminders.

Runs with the service role. A participant is due for the 24h reminder when their event starts
within the next 24 hours, they have not confirmed yet (`joined` / `matched`) and no 24h reminder
was sent; the 3h reminder works the same way for `joined` / `matched` / `confirmed_24h`. Users
who switched reminders off in their settings are skipped. After a successful send the row is
stamped (`reminded_*_at`) with an `is.null` guard, so two runners cannot both stamp it.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from ..supabase import ServiceAuth, SupabaseRest
from .notifier import Notifier

logger = logging.getLogger(__name__)

CANDIDATE_COLUMNS = (
    "id,user_id,event_id,status,"
    "events!inner(id,title,event_at,status),"
    "profiles!inner(display_name,user_settings!inner(reminders_enabled))"
)
ACTIVE_EVENT_STATUSES = "in.(open,matched,confirmed)"
BATCH = 500


@dataclass
class ReminderStats:
    sent_24h: int = 0
    sent_3h: int = 0
    failed: int = 0


@dataclass(frozen=True)
class _Pass:
    kind: str
    statuses: tuple[str, ...]
    stamp_column: str
    window: timedelta


PASSES = (
    _Pass("reminder_24h", ("joined", "matched"), "reminded_24h_at", timedelta(hours=24)),
    _Pass(
        "reminder_3h", ("joined", "matched", "confirmed_24h"), "reminded_3h_at", timedelta(hours=3)
    ),
)


async def run_reminders(
    sb: SupabaseRest, notifier: Notifier, *, now: datetime | None = None
) -> ReminderStats:
    now = now or datetime.now(UTC)
    stats = ReminderStats()
    for reminder in PASSES:
        rows = await sb.select(
            "event_participants",
            auth=ServiceAuth(),
            columns=CANDIDATE_COLUMNS,
            filters=[
                ("status", f"in.({','.join(reminder.statuses)})"),
                (reminder.stamp_column, "is.null"),
                ("events.status", ACTIVE_EVENT_STATUSES),
                ("events.event_at", f"gte.{now.isoformat()}"),
                ("events.event_at", f"lte.{(now + reminder.window).isoformat()}"),
                ("profiles.user_settings.reminders_enabled", "eq.true"),
            ],
            limit=BATCH,
        )
        for row in rows:
            if await _remind(sb, notifier, reminder, row, now):
                if reminder.kind == "reminder_24h":
                    stats.sent_24h += 1
                else:
                    stats.sent_3h += 1
            else:
                stats.failed += 1
    return stats


async def _remind(
    sb: SupabaseRest, notifier: Notifier, reminder: _Pass, row: dict[str, Any], now: datetime
) -> bool:
    event = row["events"]
    payload = {"event_id": event["id"], "event_at": event["event_at"], "title": event.get("title")}
    try:
        await notifier.send(UUID(row["user_id"]), reminder.kind, payload)
    except Exception:
        logger.exception("%s failed for participant %s; will retry", reminder.kind, row["id"])
        return False
    try:
        await sb.update(
            "event_participants",
            {reminder.stamp_column: now.isoformat()},
            auth=ServiceAuth(),
            filters=[("id", f"eq.{row['id']}"), (reminder.stamp_column, "is.null")],
            returning=False,
        )
    except Exception:
        # Notified but not stamped: the next run may notify again. Better than aborting the pass.
        logger.exception("could not stamp %s for participant %s", reminder.stamp_column, row["id"])
        return False
    return True
