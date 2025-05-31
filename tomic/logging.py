from __future__ import annotations

import logging
import os
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    """Forward standard logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        # Skip internal frames from the logging module
        logger.opt(depth=6, exception=record.exc_info).log(record.levelno, record.getMessage())


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure loguru logging based on environment variables."""

    debug_env = os.getenv("TOMIC_DEBUG", "0")
    level_name = os.getenv("TOMIC_LOG_LEVEL", "").upper()
    level = getattr(logging, level_name, default_level)

    logger.remove()
    logger.add(sys.stderr, level=level, format="{level}: {message}")

    logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)

    logger.info(
        "Logging setup: TOMIC_DEBUG=%s, TOMIC_LOG_LEVEL=%s",
        debug_env,
        level_name or logging.getLevelName(level),
    )
