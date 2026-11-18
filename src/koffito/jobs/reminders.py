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

from ..db import Database, ServiceAuth
from .notifier import Notifier

logger = logging.getLogger(__name__)

CANDIDATE_COLUMNS = (
    "id,user_id,event_id,status,"
    "events!inner(id,title,event_at,status),"
    "profiles!inner(display_name,user_settings!inner(reminders_enabled))"
)
ACTIVE_EVENT_STATUSES = ("open", "matched", "confirmed")
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
    sb: Database, notifier: Notifier, *, now: datetime | None = None
) -> ReminderStats:
    now = now or datetime.now(UTC)
    stats = ReminderStats()
    for reminder in PASSES:
        stamp = reminder.stamp_column  # one of two fixed column names (see PASSES)
        rows = await sb.fetch(
            f"""
            select ep.id, ep.user_id,
                   jsonb_build_object('id', e.id, 'event_at', e.event_at,
                                      'title', e.title) as events
            from public.event_participants ep
            join public.events e on e.id = ep.event_id
            join public.user_settings us on us.user_id = ep.user_id
            where ep.status::text = any(%s)
              and ep.{stamp} is null
              and e.status::text = any(%s)
              and e.event_at >= %s and e.event_at <= %s
              and us.reminders_enabled
            limit %s
            """,
            [
                list(reminder.statuses),
                list(ACTIVE_EVENT_STATUSES),
                now,
                now + reminder.window,
                BATCH,
            ],
            auth=ServiceAuth(),
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
    sb: Database, notifier: Notifier, reminder: _Pass, row: dict[str, Any], now: datetime
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
