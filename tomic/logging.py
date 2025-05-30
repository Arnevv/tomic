import logging
import os


class _InfoErrorFilter(logging.Filter):
    """Filter that hides INFO and ERROR messages when debug is disabled."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        debug = os.getenv("TOMIC_DEBUG", "0").lower() in {"1", "true", "yes"}
        if debug:
            return True
        return record.levelno not in (logging.INFO, logging.ERROR)


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure basic logging for scripts.

    By default INFO and ERROR messages are filtered out. Set the environment
    variable ``TOMIC_DEBUG=1`` to display them.
    """

    level_name = os.getenv("TOMIC_LOG_LEVEL", "").upper()
    level = getattr(logging, level_name, default_level)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    if os.getenv("TOMIC_DEBUG", "0").lower() not in {"1", "true", "yes"}:
        logging.getLogger().addFilter(_InfoErrorFilter())
