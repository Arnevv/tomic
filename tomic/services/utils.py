"""Shared service utilities."""

from __future__ import annotations

from typing import Any, Callable, Mapping


ConfigGetter = Callable[[str, Any | None], Any]


def resolve_config_getter(
    config: Mapping[str, Any] | ConfigGetter | None,
) -> ConfigGetter:
    """Return callable configuration getter for ``config`` input."""

    if callable(config):
        return config  # type: ignore[return-value]
    if hasattr(config, "get"):
        return lambda key, default=None: config.get(key, default)  # type: ignore[arg-type]
    if isinstance(config, Mapping):
        return lambda key, default=None: config.get(key, default)
    return lambda _key, default=None: default


__all__ = ["resolve_config_getter"]

