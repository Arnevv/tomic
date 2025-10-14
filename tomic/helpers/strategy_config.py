"""Utility helpers for looking up per-strategy configuration values."""

from __future__ import annotations

from typing import Any, Mapping


def canonical_strategy_name(strategy: str) -> str:
    """Return canonical configuration key for ``strategy``."""

    return str(strategy or "").lower().replace(" ", "_")


def get_strategy_setting(
    config: Mapping[str, Any] | None, strategy: str, key: str
) -> Any | None:
    """Return strategy specific setting ``key`` with default fallback."""

    if not isinstance(config, Mapping):
        return None

    canonical = canonical_strategy_name(strategy)

    strategies_cfg = config.get("strategies")
    if isinstance(strategies_cfg, Mapping):
        # Prefer canonical key but allow raw strategy name as fallback.
        for candidate in (canonical, strategy):
            strat_cfg = strategies_cfg.get(candidate)
            if isinstance(strat_cfg, Mapping) and key in strat_cfg:
                return strat_cfg.get(key)

    default_cfg = config.get("default")
    if isinstance(default_cfg, Mapping):
        return default_cfg.get(key)

    return None


def coerce_int(value: Any) -> int | None:
    """Convert ``value`` to ``int`` when possible, otherwise ``None``."""

    if isinstance(value, bool):  # bool is subclass of int, keep explicit
        return int(value)
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except Exception:
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return int(float(raw))
        except Exception:
            return None
    return None


__all__ = [
    "canonical_strategy_name",
    "coerce_int",
    "get_strategy_setting",
]

