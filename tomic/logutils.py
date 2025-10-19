from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar

from tomic.config import get as cfg_get
from functools import wraps
from typing import Any, Callable, Iterator, Optional, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from collections.abc import Iterable, Mapping, Sequence
    from tomic.reporting import EvaluationSummary

from tomic.strategy.reasons import (
    ReasonDetail,
    ReasonLike,
    normalize_reason as _normalize_reason,
)


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


def setup_logging(
    default_level: int = logging.INFO,
    *,
    stdout: bool = False,
) -> None:
    """Configure loguru logging based on configuration and environment."""

    debug_env = os.getenv("TOMIC_DEBUG", "0")
    level_name = os.getenv("TOMIC_LOG_LEVEL", cfg_get("LOG_LEVEL", "INFO")).upper()

    is_debug = debug_env not in {"0", "", "false", "False"}

    if is_debug and not level_name:
        default_level = logging.DEBUG

    level = getattr(logging, level_name, default_level)

    stream = sys.stdout if stdout else sys.stderr

    if _LOGURU_AVAILABLE:
        logger.remove()
        logger.add(
            stream,
            level=level,
            format="{level} - {time:HH:mm:ss}: {message}",
        )

        logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)
    else:  # pragma: no cover - fallback
        logging.basicConfig(
            level=level,
            format="%(levelname)s - %(asctime)s: %(message)s",
            datefmt="%H:%M:%S",
            stream=stream,
        )

    ib_level = logging.DEBUG if is_debug else logging.WARNING
    logging.getLogger("ibapi").setLevel(ib_level)
    logging.getLogger("ibapi.client").setLevel(ib_level)

    logger.info(
        f"Logging setup: TOMIC_DEBUG={debug_env}, "
        f"TOMIC_LOG_LEVEL={level_name or logging.getLevelName(level)}"
    )


T = TypeVar("T")


_combo_capture: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "combo_capture", default=None
)
_combo_symbol: ContextVar[str | None] = ContextVar("combo_symbol", default=None)


def log_result(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that logs function calls and their return value."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        logger.debug(f"calling {func.__name__}")
        result = func(*args, **kwargs)
        logger.debug(f"{func.__name__} -> {_format_result(result)}")
        return result

    return wrapper


@contextmanager
def capture_combo_evaluations() -> Iterator[list[dict[str, Any]]]:
    """Capture combo evaluations logged within the context."""

    captured: list[dict[str, Any]] = []
    token = _combo_capture.set(captured)
    try:
        yield captured
    finally:
        _combo_capture.reset(token)


@contextmanager
def combo_symbol_context(symbol: str | None) -> Iterator[None]:
    """Temporarily associate ``symbol`` with combo evaluation logs."""

    normalized = str(symbol).upper() if isinstance(symbol, str) and symbol else None
    token = _combo_symbol.set(normalized)
    try:
        yield
    finally:
        _combo_symbol.reset(token)


def get_captured_combo_evaluations() -> list[dict[str, Any]]:
    """Return captured combo evaluations for the active session."""

    captured = _combo_capture.get()
    return list(captured) if captured is not None else []


def normalize_reason(raw_reason: ReasonLike) -> ReasonDetail:
    """Proxy to :func:`tomic.strategy.reasons.normalize_reason`."""

    return _normalize_reason(raw_reason)


def trace_calls(func: Callable[..., T]) -> Callable[..., T]:
    """Trace all function calls triggered by ``func`` and log their results."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        debug_env = os.getenv("TOMIC_DEBUG", "0")
        level_name = os.getenv("TOMIC_LOG_LEVEL", cfg_get("LOG_LEVEL", "INFO"))
        is_debug = debug_env not in {"0", "", "false", "False"} or level_name.upper() == "DEBUG"

        if not is_debug:
            return func(*args, **kwargs)

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


def log_combo_evaluation(
    strategy: str,
    desc: str,
    metrics: Optional[dict],
    result: str,
    reason: ReasonLike,
    *,
    legs: list[dict] | None = None,
    extra: dict | None = None,
) -> None:
    """Log a strategy combination evaluation on INFO level."""

    pos = metrics.get("pos") if metrics else None
    reward = metrics.get("max_profit") if metrics else None
    max_loss = metrics.get("max_loss") if metrics else None
    ev = metrics.get("ev") if metrics else None
    rr = None
    try:
        rr = reward / abs(max_loss) if reward is not None and max_loss else None
    except Exception:
        rr = None

    pos_str = f"{round(pos, 1)}%" if isinstance(pos, (float, int)) else "n/a"
    rr_str = f"{round(rr, 2)}" if isinstance(rr, (float, int)) else "n/a"
    ev_str = f"{round(ev, 4)}" if isinstance(ev, (float, int)) else "n/a"

    extra_data: dict[str, Any] = dict(extra or {})
    symbol_hint = extra_data.get("symbol") or _combo_symbol.get()
    if symbol_hint:
        extra_data.setdefault("symbol", symbol_hint)

    extra_parts: list[str] = []
    if extra_data:
        extra_parts.extend(f"{k}={v}" for k, v in extra_data.items())
    if legs:
        expiries = sorted({str(l.get("expiry")) for l in legs if l.get("expiry")})
        if expiries:
            extra_parts.append(f"expiry={','.join(expiries)}")
        for leg in legs:
            typ = str(leg.get("type") or "").upper()[:1]
            strike = leg.get("strike")
            pos = leg.get("position")
            if strike is None or not typ:
                continue
            label = ("S" if pos is not None and float(pos) < 0 else "L") + (
                "C" if typ == "C" else "P"
            )
            extra_parts.append(f"{label}={strike}{typ}")
    extra_str = " | " + " | ".join(extra_parts) if extra_parts else ""

    detail = normalize_reason(reason)
    logger.info(
        f"[{strategy}] {desc} — PoS {pos_str}, RR {rr_str}, EV {ev_str} — {result.upper()} ({detail.message}){extra_str}"
    )

    captured = _combo_capture.get()
    if captured is not None:
        record = {
            "strategy": strategy,
            "status": result,
            "description": desc,
            "legs": list(legs or []),
            "metrics": dict(metrics or {}),
            "raw_reason": detail.message,
            "reason": detail,
            "meta": dict(extra_data),
        }
        if symbol_hint:
            record["symbol"] = symbol_hint
        captured.append(record)


def summarize_evaluations(
    evaluations: "Sequence[Mapping[str, Any]] | Iterable[Mapping[str, Any]]",
) -> "EvaluationSummary | None":
    """Delegate to :func:`tomic.reporting.summarize_evaluations` lazily."""

    from tomic.reporting import summarize_evaluations as _summarize  # local import

    return _summarize(evaluations)

