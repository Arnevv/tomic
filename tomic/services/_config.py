"""Shared configuration helpers for service modules."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from tomic.config import get as cfg_get


_DEFAULT_EXIT_SPREAD_ABSOLUTE = 0.50
_DEFAULT_EXIT_SPREAD_RELATIVE = 0.12
_DEFAULT_EXIT_MAX_QUOTE_AGE = 5.0
_DEFAULT_EXIT_REPRICER_WAIT = 10.0


def cfg_value(key: str, default: Any) -> Any:
    """Return configuration value or ``default`` when unset or empty."""

    value = cfg_get(key, default)
    if value is None:
        return default
    if isinstance(value, str) and value == "":
        return default
    return value


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def exit_spread_config() -> dict[str, Any]:
    """Return normalized spread configuration for exit order checks."""

    options = _as_mapping(cfg_value("EXIT_ORDER_OPTIONS", {}))
    spread_raw = _as_mapping(options.get("spread"))

    absolute_default = _coerce_float(
        cfg_value("EXIT_SPREAD_ABSOLUTE", _DEFAULT_EXIT_SPREAD_ABSOLUTE),
        _DEFAULT_EXIT_SPREAD_ABSOLUTE,
    )
    relative_default = _coerce_float(
        cfg_value("EXIT_SPREAD_RELATIVE", _DEFAULT_EXIT_SPREAD_RELATIVE),
        _DEFAULT_EXIT_SPREAD_RELATIVE,
    )
    max_age_default = _coerce_float(
        cfg_value("EXIT_MAX_QUOTE_AGE", _DEFAULT_EXIT_MAX_QUOTE_AGE),
        _DEFAULT_EXIT_MAX_QUOTE_AGE,
    )

    absolute = _coerce_float(spread_raw.get("absolute"), absolute_default)
    relative = _coerce_float(spread_raw.get("relative"), relative_default)
    max_age = _coerce_float(spread_raw.get("max_quote_age"), max_age_default)

    return {
        "absolute": max(0.0, absolute),
        "relative": max(0.0, relative),
        "max_quote_age": max(0.0, max_age),
    }


def exit_repricer_config() -> dict[str, Any]:
    """Return repricer tuning for exit orders."""

    options = _as_mapping(cfg_value("EXIT_ORDER_OPTIONS", {}))
    repricer_raw = _as_mapping(options.get("repricer"))

    enabled_default = _coerce_bool(cfg_value("EXIT_REPRICER_ENABLED", True), True)
    wait_default = _coerce_float(
        cfg_value("EXIT_REPRICER_WAIT_SECONDS", _DEFAULT_EXIT_REPRICER_WAIT),
        _DEFAULT_EXIT_REPRICER_WAIT,
    )

    enabled = _coerce_bool(repricer_raw.get("enabled"), enabled_default)
    wait_seconds = _coerce_float(repricer_raw.get("wait_seconds"), wait_default)

    return {
        "enabled": enabled,
        "wait_seconds": max(0.0, wait_seconds),
    }


def exit_fallback_config() -> dict[str, Any]:
    """Return fallback policy for exit order validation."""

    options = _as_mapping(cfg_value("EXIT_ORDER_OPTIONS", {}))
    fallback_raw = _as_mapping(options.get("fallback"))

    allow_preview_default = _coerce_bool(
        cfg_value("EXIT_FALLBACK_ALLOW_PREVIEW", False),
        False,
    )
    allowed_sources_default = cfg_value("EXIT_FALLBACK_ALLOWED_SOURCES", []) or []

    allow_preview = _coerce_bool(
        fallback_raw.get("allow_preview"),
        allow_preview_default,
    )
    sources_raw: Iterable[Any] = fallback_raw.get("allowed_sources", allowed_sources_default)
    allowed_sources = {
        str(item).strip().lower()
        for item in (sources_raw or [])
        if str(item).strip()
    }

    return {
        "allow_preview": allow_preview,
        "allowed_sources": allowed_sources,
    }


def exit_force_exit_config() -> dict[str, Any]:
    """Return forced exit policy configuration."""

    options = _as_mapping(cfg_value("EXIT_ORDER_OPTIONS", {}))
    force_option = options.get("force_exit")

    enabled_default = _coerce_bool(cfg_value("EXIT_FORCE_EXIT_ENABLED", False), False)
    market_default = _coerce_bool(
        cfg_value("EXIT_FORCE_EXIT_MARKET_ORDER", False),
        False,
    )

    if isinstance(force_option, Mapping):
        force_raw = force_option
        enabled = _coerce_bool(force_raw.get("enabled"), enabled_default)
        market_order = _coerce_bool(force_raw.get("market_order"), market_default)
        limit_cap_raw = _as_mapping(force_raw.get("limit_cap"))
    else:
        force_raw = {}
        if force_option is None:
            enabled = enabled_default
        else:
            enabled = _coerce_bool(force_option, enabled_default)
        market_order = market_default
        limit_cap_raw = {}

    limit_cap: dict[str, Any] | None = None
    cap_type = str(limit_cap_raw.get("type") or "").strip().lower()
    cap_value = _coerce_float(limit_cap_raw.get("value"), 0.0)
    if cap_type in {"absolute", "bps"} and cap_value > 0:
        limit_cap = {"type": cap_type, "value": cap_value}

    return {"enabled": enabled, "market_order": market_order, "limit_cap": limit_cap}


def exit_price_ladder_config() -> dict[str, Any]:
    """Return configuration for incremental exit price adjustments."""

    options = _as_mapping(cfg_value("EXIT_ORDER_OPTIONS", {}))
    ladder_raw = _as_mapping(options.get("price_ladder"))

    enabled = _coerce_bool(ladder_raw.get("enabled"), False)

    raw_steps = ladder_raw.get("steps", []) or []
    steps: list[float] = []
    for value in raw_steps:
        try:
            steps.append(float(value))
        except (TypeError, ValueError):
            continue

    if "step_wait_seconds" in ladder_raw:
        wait_seconds = _coerce_float(ladder_raw.get("step_wait_seconds"), 0.0)
    elif "step_wait_s" in ladder_raw:
        wait_seconds = _coerce_float(ladder_raw.get("step_wait_s"), 0.0)
    elif "step_wait_ms" in ladder_raw:
        wait_seconds = _coerce_float(ladder_raw.get("step_wait_ms"), 0.0) / 1000.0
    else:
        wait_seconds = 0.0

    if "max_duration_seconds" in ladder_raw:
        max_duration = _coerce_float(ladder_raw.get("max_duration_seconds"), 0.0)
    else:
        max_duration = _coerce_float(ladder_raw.get("max_duration_s"), 0.0)

    return {
        "enabled": enabled,
        "steps": steps,
        "step_wait_seconds": max(0.0, wait_seconds),
        "max_duration_seconds": max(0.0, max_duration),
    }


__all__ = [
    "cfg_value",
    "exit_spread_config",
    "exit_repricer_config",
    "exit_fallback_config",
    "exit_force_exit_config",
    "exit_price_ladder_config",
]
