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


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure basic logging for scripts.

    The environment variable ``TOMIC_DEBUG=1`` shows additional I/O logs.
    """

    level_name = os.getenv("TOMIC_LOG_LEVEL", "").upper()
    level = getattr(logging, level_name, default_level)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    logging.getLogger("tomic.io")
    logging.getLogger("tomic.status")
    logging.getLogger("tomic.warning")

    if os.getenv("TOMIC_DEBUG", "0").lower() not in {"1", "true", "yes"}:
        root_logger = logging.getLogger()
        root_logger.addFilter(_IoFilter())
        root_logger.addFilter(_InfoErrorFilter())

