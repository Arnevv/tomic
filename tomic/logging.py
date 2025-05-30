import logging
import os


class _IoFilter(logging.Filter):
    """Filter that hides ``tomic.io`` logs when debug is disabled."""

    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        debug = os.getenv("TOMIC_DEBUG", "0").lower() in {"1", "true", "yes"}
        if debug:
            return True
        return record.name != "tomic.io"


class _InfoErrorFilter(logging.Filter):
    """Filter INFO/ERROR logs unless debugging or containing status emojis."""

    def filter(self, record: logging.LogRecord) -> bool:
        debug = os.getenv("TOMIC_DEBUG", "0").lower() in {"1", "true", "yes"}

        msg = record.getMessage()

        if any(emoji in msg for emoji in ("✅", "📊", "⏳", "⚠️")):
            return True

        if any(msg.startswith(prefix) for prefix in ("SENDING", "REQUEST", "ANSWER")):
            return debug

        if record.levelno in (logging.INFO, logging.ERROR):
            return debug

        return True


def setup_logging(default_level: int = logging.WARNING) -> None:
    """Configure basic logging for scripts.

    The environment variable ``TOMIC_DEBUG=1`` shows additional I/O logs.
    """

    debug_env = os.getenv("TOMIC_DEBUG", "0")
    level_name = os.getenv("TOMIC_LOG_LEVEL", "").upper()
    level = getattr(logging, level_name, default_level)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    # Log the resolved environment configuration so users can verify settings
    logging.getLogger(__name__).info(
        "Logging setup: TOMIC_DEBUG=%s, TOMIC_LOG_LEVEL=%s", debug_env, level_name or logging.getLevelName(level)
    )

    logging.getLogger("tomic.io")
    logging.getLogger("tomic.status")
    logging.getLogger("tomic.warning")

    if os.getenv("TOMIC_DEBUG", "0").lower() not in {"1", "true", "yes"}:
        root_logger = logging.getLogger()
        root_logger.addFilter(_IoFilter())
        root_logger.addFilter(_InfoErrorFilter())

