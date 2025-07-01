"""Minimal loader utilities for strike configuration."""

from __future__ import annotations


def load_strike_config(strategy_name: str, config: dict) -> dict:
    """Return strike config for ``strategy_name`` with ``default`` fallback."""

    return config["strategies"].get(strategy_name, config["default"])
