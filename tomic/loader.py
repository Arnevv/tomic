"""Minimal loader utilities for strike configuration."""

from __future__ import annotations

from typing import Mapping, MutableMapping
import warnings


def normalize_strike_rule_fields(
    rules: Mapping[str, object], strategy: str | None = None
) -> dict:
    """Return ``rules`` with deprecated keys mapped to canonical names.

    Parameters
    ----------
    rules:
        Mapping of configuration options to normalize.
    strategy:
        Optional strategy name used for strategy specific field mappings.
    """

    mapping: dict[str, str] = {
        "long_leg_distance": "long_leg_distance_points",
        "long_leg_distance_points": "long_leg_target_delta",
        "strike_distance": "base_strikes_relative_to_spot",
        "expiry_gap_min": "expiry_gap_min_days",
        "wing_width": "wing_width_points",
        "wing_width_points": "wing_width_sigma",
    }
    per_strategy: dict[str, dict[str, str]] = {
        "backspread_put": {"short_delta_range": "short_put_delta_range"},
        "naked_put": {"short_delta_range": "short_put_delta_range"},
        "short_put_spread": {"short_delta_range": "short_put_delta_range"},
        "short_call_spread": {"short_delta_range": "short_call_delta_range"},
        "ratio_spread": {"short_delta_range": "short_leg_delta_range"},
    }
    if strategy and strategy in per_strategy:
        mapping.update(per_strategy[strategy])

    normalized: MutableMapping[str, object] = dict(rules)
    for old, new in mapping.items():
        if old in normalized and new not in normalized:
            val = normalized.pop(old)
            warnings.warn(
                f"'{old}' is deprecated; use '{new}' instead",
                DeprecationWarning,
                stacklevel=2,
            )
            normalized[new] = val
        else:
            normalized.pop(old, None)

    # promote new fields without deprecation warnings
    if "wing_width_sigma" in normalized and "wing_sigma_multiple" not in normalized:
        normalized["wing_sigma_multiple"] = normalized.pop("wing_width_sigma")

    b = normalized.get("base_strikes_relative_to_spot")
    if b is not None and not isinstance(b, (list, tuple)):
        normalized["base_strikes_relative_to_spot"] = [b]

    w = normalized.get("wing_sigma_multiple")
    if isinstance(w, (list, tuple)):
        normalized["wing_sigma_multiple"] = w[0] if w else w

    return dict(normalized)


def load_strike_config(strategy_name: str, config: dict) -> dict:
    """Return strike config for ``strategy_name`` with ``default`` fallback.

    ``config`` can be structured in two ways:

    1. ``{"default": {...}, "strategies": {"s1": {...}}}``
    2. ``{"default": {...}, "s1": {...}}``

    This helper detects the layout and returns the rule set for ``strategy_name``
    or falls back to ``default`` when not found. Missing keys simply return an
    empty dict so callers don't need defensive ``try`` blocks.
    """

    if "strategies" in config:
        rules = config["strategies"].get(strategy_name, config.get("default", {}))
    else:
        rules = config.get(strategy_name, config.get("default", {}))

    return normalize_strike_rule_fields(rules or {}, strategy_name)
