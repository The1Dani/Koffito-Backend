import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ..db import Database
from .completion import run_completion
from .matchmaking import run_matchmaking
from .notifier import LoggingNotifier, Notifier
from .reminders import run_reminders
from .venues import run_venue_assignment

logger = logging.getLogger(__name__)

JobFn = Callable[[Database, Notifier], Awaitable[Any]]


async def _reminders(sb: Database, notifier: Notifier) -> Any:
    return await run_reminders(sb, notifier)


async def _matchmaking(sb: Database, notifier: Notifier) -> Any:
    return await run_matchmaking(sb)


async def _venues(sb: Database, notifier: Notifier) -> Any:
    return await run_venue_assignment(sb)


async def _completion(sb: Database, notifier: Notifier) -> Any:
    return await run_completion(sb)


# Run order: freshly matched groups get a café in the same tick, then reminders go out.
JOBS: dict[str, JobFn] = {
    "matchmaking": _matchmaking,
    "venues": _venues,
    "reminders": _reminders,
    "completion": _completion,
}


async def run_job(name: str, sb: Database, notifier: Notifier) -> Any:
    """Run one job once; exceptions propagate to the caller."""
    started = time.monotonic()
    result = await JOBS[name](sb, notifier)
    logger.info("job %s finished in %.1fs: %s", name, time.monotonic() - started, result)
    return result


async def run_forever(
    sb: Database,
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
