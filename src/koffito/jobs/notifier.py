import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from ..auth.mailer import Mailer
from ..core.config import Settings
from ..db import Database, ServiceAuth

logger = logging.getLogger(__name__)

NotificationKind = Literal["reminder_24h", "reminder_3h"]


class Notifier(Protocol):
    """Delivers a notification to one user. Raise to signal failure (the job retries later)."""

    async def send(self, user_id: UUID, kind: str, payload: Mapping[str, Any]) -> None: ...


class LoggingNotifier:
    """Logs instead of sending (tests, or when email is not wanted)."""

    async def send(self, user_id: UUID, kind: str, payload: Mapping[str, Any]) -> None:
        logger.info("notify user=%s kind=%s event=%s", user_id, kind, payload.get("event_id"))


class EmailNotifier:
    """Sends coffee-talk reminders by email. Raising leaves the reminder for the next run."""

    def __init__(self, db: Database, mailer: Mailer, settings: Settings) -> None:
        self._db = db
        self._mailer = mailer
        self._tz = ZoneInfo(settings.app_timezone)

    async def send(self, user_id: UUID, kind: str, payload: Mapping[str, Any]) -> None:
        row = await self._db.fetchrow(
            "select email::text as email from public.users where id = %s and email_verified_at"
            " is not null",
            [user_id],
            auth=ServiceAuth(),
        )
        if row is None:
            logger.info("no confirmed email for user %s; skipping %s", user_id, kind)
            return
        at = datetime.fromisoformat(str(payload["event_at"])).astimezone(self._tz)
        await self._mailer.send(
            self._mailer.reminder(row["email"], kind, at, str(payload["event_id"]))
        )
