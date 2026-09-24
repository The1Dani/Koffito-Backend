"""One-shot / looping job runner: `python -m koffito.jobs <reminders|matchmaking|venues|all>`."""

import argparse
import asyncio
import logging
import sys

import httpx

from ..core.config import Settings
from ..core.logging import configure_logging
from ..supabase import SupabaseRest
from .notifier import LoggingNotifier
from .runner import JOBS, run_forever, run_job

logger = logging.getLogger("koffito.jobs")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m koffito.jobs")
    parser.add_argument("job", choices=[*JOBS, "all"])
    parser.add_argument("--loop", action="store_true", help="keep running every --interval s")
    parser.add_argument("--interval", type=float, default=None, help="loop interval in seconds")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    service_key = settings.supabase_service_role_key
    if service_key is None:
        logger.error("SUPABASE_SERVICE_ROLE_KEY is required to run jobs")
        return 2
    names = list(JOBS) if args.job == "all" else [args.job]
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.supabase_timeout_seconds)) as http:
        sb = SupabaseRest(
            http,
            rest_url=settings.rest_url,
            publishable_key=settings.supabase_publishable_key,
            service_key=service_key.get_secret_value(),
            backend_key=settings.koffito_backend_key.get_secret_value(),
        )
        notifier = LoggingNotifier()
        if args.loop:
            interval = args.interval or settings.jobs_interval_seconds
            await run_forever(sb, interval=interval, notifier=notifier, names=names)
            return 0
        failed = False
        for name in names:
            try:
                await run_job(name, sb, notifier)
            except Exception:
                logger.exception("job %s failed", name)
                failed = True
        return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        return asyncio.run(_run(args, settings))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
