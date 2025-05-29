import logging
import os


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure basic logging for scripts."""
    level_name = os.getenv("TOMIC_LOG_LEVEL", "").upper()
    level = getattr(logging, level_name, default_level)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
