import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..supabase import SupabaseRest
from .matchmaking import run_matchmaking
from .notifier import LoggingNotifier, Notifier
from .reminders import run_reminders
from .venues import run_venue_assignment

logger = logging.getLogger(__name__)

JobFn = Callable[[SupabaseRest, Notifier], Awaitable[Any]]


async def _reminders(sb: SupabaseRest, notifier: Notifier) -> Any:
    return await run_reminders(sb, notifier)


async def _matchmaking(sb: SupabaseRest, notifier: Notifier) -> Any:
    return await run_matchmaking(sb)


async def _venues(sb: SupabaseRest, notifier: Notifier) -> Any:
    return await run_venue_assignment(sb)


JOBS: dict[str, JobFn] = {
    "reminders": _reminders,
    "matchmaking": _matchmaking,
    "venues": _venues,
}


async def run_job(name: str, sb: SupabaseRest, notifier: Notifier) -> Any:
    """Run one job once; exceptions propagate to the caller."""
    started = time.monotonic()
    result = await JOBS[name](sb, notifier)
    logger.info("job %s finished in %.1fs: %s", name, time.monotonic() - started, result)
    return result


async def run_forever(
    sb: SupabaseRest,
    *,
    interval: float,
    notifier: Notifier | None = None,
    names: Iterable[str] | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Run the jobs sequentially every `interval` seconds until cancelled (or `stop` is set).

    Meant for a single instance (`JOBS_ENABLED=true`). Several replicas should run
    `python -m koffito.jobs all` from one cron instead.
    """
    notifier = notifier or LoggingNotifier()
    names = list(names or JOBS)
    stop = stop or asyncio.Event()
    while not stop.is_set():
        for name in names:
            try:
                await run_job(name, sb, notifier)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("job %s failed", name)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue
