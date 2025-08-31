"""Minimal loader utilities for strike configuration."""

from __future__ import annotations


def normalize_strike_rule_fields(rules: dict) -> dict:
    """Return ``rules`` with deprecated keys mapped to canonical names."""

    mapping = {
        "long_leg_distance": "long_leg_distance_points",
        "strike_distance": "base_strikes_relative_to_spot",
        "expiry_gap_min": "expiry_gap_min_days",
    }
    normalized = dict(rules)
    for old, new in mapping.items():
        if old in normalized and new not in normalized:
            normalized[new] = normalized.pop(old)
        else:
            normalized.pop(old, None)
    b = normalized.get("base_strikes_relative_to_spot")
    if b is not None and not isinstance(b, (list, tuple)):
        normalized["base_strikes_relative_to_spot"] = [b]
    return normalized


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

    return normalize_strike_rule_fields(rules or {})
