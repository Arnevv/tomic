"""Configuration related helpers shared across services."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Tuple

from ..core.config.strike_selection import load_strategy_rules
from ..strike_selector import load_filter_config
from .strategy_config import canonical_strategy_name


def load_dte_range(
    strategy: str,
    config: Mapping[str, Any] | None,
    *,
    rules: Mapping[str, Any] | None = None,
    loader: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None = None,
    default: Tuple[int, int] = (0, 365),
) -> Tuple[int, int]:
    """Return configured DTE range for ``strategy`` falling back to ``default``."""

    base_config: Mapping[str, Any] = config or {}

    resolved_rules: Mapping[str, Any] | None = rules
    if resolved_rules is None and loader is not None:
        try:
            resolved_rules = loader(strategy, base_config)
        except Exception:  # pragma: no cover - defensive guard
            resolved_rules = None

    if resolved_rules is None:
        try:
            resolved_rules = load_strategy_rules(
                canonical_strategy_name(strategy), dict(base_config)
            )
        except Exception:  # pragma: no cover - defensive guard
            resolved_rules = {}

    rules_mapping = dict(resolved_rules or {})
    config_range = load_filter_config(rules=rules_mapping).dte_range

    if "dte_range" not in rules_mapping:
        return int(default[0]), int(default[1])

    return config_range


__all__ = ["load_dte_range"]

