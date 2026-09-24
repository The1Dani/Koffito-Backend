import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
        force=True,
    )
    # httpx logs every request URL at INFO; keep tokens/keys out of the logs by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
