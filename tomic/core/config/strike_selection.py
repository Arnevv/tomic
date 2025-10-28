"""Typed loader for strike selection configuration."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...config import _load_yaml


def _as_tuple(value: Any) -> tuple[float | int, float | int] | None:
    """Return ``value`` coerced to a tuple when possible."""

    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        return value
    if isinstance(value, list) and len(value) == 2:
        return value[0], value[1]
    return None


def _canonical_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


class StrikeSelectionRule(BaseModel):
    """Single strategy strike selection rule set."""

    method: str | None = None
    delta_range: tuple[float | int, float | int] | None = Field(default=None)
    short_delta_range: tuple[float | int, float | int] | None = Field(default=None)
    dte_range: tuple[int, int] | None = Field(default=None)
    stddev_range: float | tuple[float | int, float | int] | None = Field(default=None)
    max_strikes: int | None = None

    model_config = ConfigDict(extra="allow")

    @field_validator("delta_range", "short_delta_range", mode="before")
    @classmethod
    def _coerce_float_tuple(
        cls, value: Any
    ) -> tuple[float | int, float | int] | None:
        converted = _as_tuple(value)
        if converted is None:
            return None
        first, second = converted
        try:
            return float(first), float(second)
        except Exception:  # pragma: no cover - defensive guard
            return None

    @field_validator("dte_range", mode="before")
    @classmethod
    def _coerce_int_tuple(cls, value: Any) -> tuple[int, int] | None:
        converted = _as_tuple(value)
        if converted is None:
            return None
        try:
            first = int(converted[0])
            second = int(converted[1])
            return first, second
        except Exception:  # pragma: no cover - defensive guard
            return None


class StrikeSelectionConfig(BaseModel):
    """Complete strike selection configuration loaded from YAML."""

    default: StrikeSelectionRule = Field(default_factory=StrikeSelectionRule)
    strategies: dict[str, StrikeSelectionRule] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StrikeSelectionConfig":
        strategies: MutableMapping[str, StrikeSelectionRule] = {}

        default_data = data.get("default") if isinstance(data.get("default"), Mapping) else {}
        default_rule = StrikeSelectionRule(**dict(default_data or {}))

        provided_strategies = data.get("strategies")
        if isinstance(provided_strategies, Mapping):
            for name, raw in provided_strategies.items():
                if isinstance(raw, Mapping):
                    strategies[_canonical_name(name)] = StrikeSelectionRule(**dict(raw))

        for name, raw in data.items():
            if name in {"default", "strategies"}:
                continue
            if name not in strategies and isinstance(raw, Mapping):
                strategies[_canonical_name(name)] = StrikeSelectionRule(**dict(raw))

        return cls(default=default_rule, strategies=dict(strategies))

    def for_strategy(self, strategy: str) -> StrikeSelectionRule:
        key = _canonical_name(strategy)
        base = self.default.model_dump(exclude_none=True)
        override = self.strategies.get(key)
        if override is not None:
            base.update(override.model_dump(exclude_none=True))
        return StrikeSelectionRule(**base)


_DEFAULT_PATH = Path(
    os.environ.get("TOMIC_STRIKE_SELECTION_RULES", "") or
    Path(__file__).resolve().parents[2] / "strike_selection_rules.yaml"
)


def _load_config(path: Path | None = None) -> StrikeSelectionConfig:
    target = path or _DEFAULT_PATH
    data = _load_yaml(target)
    if not isinstance(data, Mapping):
        return StrikeSelectionConfig()
    return StrikeSelectionConfig.from_mapping(data)


@lru_cache(maxsize=None)
def load(path: Path | None = None) -> StrikeSelectionConfig:
    """Return cached strike selection configuration."""

    return _load_config(path)


def reload(path: Path | None = None) -> StrikeSelectionConfig:
    """Reload configuration bypassing the cache."""

    load.cache_clear()
    return load(path)


def load_strategy_rules(
    strategy: str,
    _config: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Return resolved rule mapping for ``strategy``.

    The ``_config`` argument is accepted for API compatibility but ignored.
    """

    cfg = load()
    rule = cfg.for_strategy(strategy)
    return rule.model_dump(exclude_none=True)


__all__ = [
    "StrikeSelectionConfig",
    "StrikeSelectionRule",
    "load",
    "reload",
    "load_strategy_rules",
]

