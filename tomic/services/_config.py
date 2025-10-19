"""Shared configuration helpers for service modules."""
from __future__ import annotations

from typing import Any

from tomic.config import get as cfg_get


def cfg_value(key: str, default: Any) -> Any:
    """Return configuration value or ``default`` when unset or empty."""

    value = cfg_get(key, default)
    return default if value in {None, ""} else value


__all__ = ["cfg_value"]
