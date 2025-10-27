"""Configuration related helpers shared across services."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence, Tuple

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

    raw_range: Sequence[Any] | None = None
    if isinstance(resolved_rules, Mapping):
        candidate = resolved_rules.get("dte_range")
        if isinstance(candidate, Sequence):
            raw_range = candidate

    if raw_range is None:
        strategies_cfg = base_config.get("strategies") if isinstance(base_config, Mapping) else None
        if isinstance(strategies_cfg, Mapping):
            for name in (canonical_strategy_name(strategy), strategy):
                strat_cfg = strategies_cfg.get(name)
                if isinstance(strat_cfg, Mapping):
                    candidate = strat_cfg.get("dte_range")
                    if isinstance(candidate, Sequence):
                        raw_range = candidate
                        break
        if raw_range is None and isinstance(base_config.get("default"), Mapping):
            candidate = base_config["default"].get("dte_range")  # type: ignore[index]
            if isinstance(candidate, Sequence):
                raw_range = candidate

    if isinstance(raw_range, Sequence) and len(raw_range) >= 2:
        try:
            return int(raw_range[0]), int(raw_range[1])
        except Exception:  # pragma: no cover - defensive guard
            return default

    return default


__all__ = ["load_dte_range"]

