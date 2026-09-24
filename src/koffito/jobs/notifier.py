import logging
from collections.abc import Mapping
from typing import Any, Literal, Protocol
from uuid import UUID

logger = logging.getLogger(__name__)

NotificationKind = Literal["reminder_24h", "reminder_3h"]


class Notifier(Protocol):
    """Delivers a notification to one user. Raise to signal failure (the job retries later)."""

    async def send(self, user_id: UUID, kind: str, payload: Mapping[str, Any]) -> None: ...


class LoggingNotifier:
    """Default notifier: logs instead of sending. TODO: Expo push (needs device tokens)."""

    async def send(self, user_id: UUID, kind: str, payload: Mapping[str, Any]) -> None:
        logger.info("notify user=%s kind=%s event=%s", user_id, kind, payload.get("event_id"))
