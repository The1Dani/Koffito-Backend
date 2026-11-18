"""One-shot / looping job runner: `python -m koffito.jobs <reminders|matchmaking|venues|all>`."""

import argparse
import asyncio
import logging
import sys

from ..auth.mailer import Mailer
from ..core.config import Settings
from ..core.logging import configure_logging
from ..db import Database
from .notifier import EmailNotifier
from .runner import JOBS, run_forever, run_job

logger = logging.getLogger("koffito.jobs")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m koffito.jobs")
    parser.add_argument("job", choices=[*JOBS, "all"])
    parser.add_argument("--loop", action="store_true", help="keep running every --interval s")
    parser.add_argument("--interval", type=float, default=None, help="loop interval in seconds")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    names = list(JOBS) if args.job == "all" else [args.job]
    db = Database(settings.database_url.get_secret_value(), max_size=4)
    await db.open()
    try:
        notifier = EmailNotifier(db, Mailer(settings), settings)
        if args.loop:
            interval = args.interval or settings.jobs_interval_seconds
            await run_forever(db, interval=interval, notifier=notifier, names=names)
            return 0
        failed = False
        for name in names:
            try:
                await run_job(name, db, notifier)
            except Exception:
                logger.exception("job %s failed", name)
                failed = True
        return 1 if failed else 0
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        # psycopg's async driver needs a selector loop (Windows defaults to Proactor).
        return asyncio.run(_run(args, settings), loop_factory=asyncio.SelectorEventLoop)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
