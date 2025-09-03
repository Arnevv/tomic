"""Minimal loader utilities for strike configuration."""

from __future__ import annotations

from .helpers.normalize import normalize_config


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

    return normalize_config(rules or {}, strategy=strategy_name)
