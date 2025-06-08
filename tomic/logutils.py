from __future__ import annotations

import logging
import os
import sys

from tomic.config import get as cfg_get
from functools import wraps
from typing import Any, Callable, TypeVar


def _format_result(result: Any, max_length: int = 200) -> str:
    """Return a string representation of ``result`` truncated if necessary."""
    if isinstance(result, str) and len(result) > max_length:
        return f"{result[:max_length]}... [truncated {len(result)} chars]"
    return str(result)

try:
    from loguru import logger  # type: ignore

    _LOGURU_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    import logging as _logging

    logger = _logging.getLogger("tomic")
    _LOGURU_AVAILABLE = False

if not hasattr(logger, "success"):

    def _success(message: str, *args: object, **kwargs: object) -> None:
        """Fallback for loguru's ``success`` method using ``info`` level."""
        logger.info(message, *args, **kwargs)

    setattr(logger, "success", _success)


class InterceptHandler(logging.Handler):
    """Forward standard logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        # Skip internal frames from the logging module
        if _LOGURU_AVAILABLE:
            logger.opt(depth=6, exception=record.exc_info).log(
                record.levelno, record.getMessage()
            )
        else:  # pragma: no cover - fallback
            logger.log(record.levelno, record.getMessage())


def setup_logging(default_level: int = logging.INFO) -> None:
    """Configure loguru logging based on configuration and environment."""

    debug_env = os.getenv("TOMIC_DEBUG", "0")
    level_name = os.getenv("TOMIC_LOG_LEVEL", cfg_get("LOG_LEVEL", "INFO")).upper()

    is_debug = debug_env not in {"0", "", "false", "False"}

    if is_debug and not level_name:
        default_level = logging.DEBUG

    level = getattr(logging, level_name, default_level)

    if _LOGURU_AVAILABLE:
        logger.remove()
        logger.add(
            sys.stderr,
            level=level,
            format="{level} - {time:HH:mm:ss}: {message}",
        )

        logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)
    else:  # pragma: no cover - fallback
        logging.basicConfig(
            level=level,
            format="%(levelname)s - %(asctime)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    ib_level = logging.DEBUG if is_debug else logging.WARNING
    logging.getLogger("ibapi").setLevel(ib_level)
    logging.getLogger("ibapi.client").setLevel(ib_level)

    logger.info(
        f"Logging setup: TOMIC_DEBUG={debug_env}, "
        f"TOMIC_LOG_LEVEL={level_name or logging.getLevelName(level)}"
    )


T = TypeVar("T")


def log_result(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that logs function calls and their return value."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        logger.debug(f"calling {func.__name__}")
        result = func(*args, **kwargs)
        logger.debug(f"{func.__name__} -> {_format_result(result)}")
        return result

    return wrapper


def trace_calls(func: Callable[..., T]) -> Callable[..., T]:
    """Trace all function calls triggered by ``func`` and log their results."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        def tracer(frame, event, arg):
            if event not in {"call", "return"}:
                return tracer
            module = frame.f_globals.get("__name__", "")
            if not module.startswith("tomic"):
                return tracer
            name = frame.f_code.co_name
            if event == "call":
                logger.debug(f"calling {module}.{name}")
            elif event == "return":
                logger.debug(f"{module}.{name} -> {_format_result(arg)}")
            return tracer

        old_profiler = sys.getprofile()
        sys.setprofile(tracer)
        try:
            return func(*args, **kwargs)
        finally:
            sys.setprofile(old_profiler)

    return wrapper

