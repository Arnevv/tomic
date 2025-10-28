"""Spread evaluation policy shared between pricing and order services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


def _coerce_float(value: Any) -> float | None:
    """Return ``value`` as ``float`` when possible."""

    if isinstance(value, (int, float)):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed:  # NaN
            return None
        return parsed
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except (TypeError, ValueError):
            return None
        if parsed != parsed:
            return None
        return parsed
    return None


def _as_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (list, tuple)):
        return value
    if value is None:
        return []
    return [value]


@dataclass(frozen=True)
class SpreadDecision:
    """Decision returned by :class:`SpreadPolicy.evaluate`."""

    accepted: bool
    reason: str
    threshold: float | None
    absolute: float | None
    relative: float | None
    rule: str | None = None


@dataclass(frozen=True)
class _SpreadBucket:
    limit: float | None
    threshold: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "_SpreadBucket | None":
        try:
            raw_limit = data.get("max_underlying")
            raw_threshold = data.get("threshold")
        except AttributeError:
            return None
        threshold = _coerce_float(raw_threshold)
        if threshold is None:
            return None
        limit = _coerce_float(raw_limit)
        return cls(limit, max(0.0, float(threshold)))

    def matches(self, underlying: float | None) -> bool:
        if self.limit is None:
            return True
        if underlying is None:
            return False
        return float(underlying) <= self.limit + 1e-12


class _SpreadRule:
    """Resolved spread thresholds for a specific rule."""

    def __init__(
        self,
        *,
        name: str,
        relative: float | None,
        absolute: float | None,
        buckets: Sequence[_SpreadBucket],
    ) -> None:
        self._name = name
        self._relative = None if relative is None else max(0.0, float(relative))
        self._absolute = None if absolute is None else max(0.0, float(absolute))
        self._buckets = tuple(bucket for bucket in buckets if bucket is not None)

    @property
    def name(self) -> str:
        return self._name

    @property
    def relative_factor(self) -> float | None:
        return self._relative

    def absolute_threshold(self, underlying: float | None) -> float | None:
        if self._absolute is not None:
            return self._absolute
        for bucket in self._buckets:
            if bucket.matches(underlying):
                return bucket.threshold
        return None

    def relative_threshold(self, mid: float | None) -> float | None:
        if mid is None or mid <= 0:
            return None
        if self._relative is None:
            return None
        return self._relative * float(mid)


class _ExceptionRule:
    """Exception-driven override for spread thresholds."""

    def __init__(
        self,
        *,
        name: str,
        match: Mapping[str, Any],
        rule: _SpreadRule,
    ) -> None:
        self._name = name
        self._rule = rule
        normalized: dict[str, Any] = {}
        for key, value in (match or {}).items():
            normalized[key] = value
        self._match = normalized

    @property
    def name(self) -> str:
        return self._name

    @property
    def rule(self) -> _SpreadRule:
        return self._rule

    def matches(
        self,
        *,
        context: Mapping[str, Any] | None,
        mid: float | None,
        underlying: float | None,
        spread: float | None,
    ) -> bool:
        data = context or {}
        for key, expected in self._match.items():
            if key in {"symbol", "structure", "strategy", "right", "source"}:
                actual = data.get(key)
                if not _match_text(actual, expected):
                    return False
            elif key == "leg_count":
                actual = data.get("leg_count")
                if actual is None:
                    return False
                allowed = {_coerce_int(item) for item in _as_sequence(expected)}
                allowed.discard(None)
                if int(actual) not in allowed:
                    return False
            elif key == "leg_count_min":
                actual = data.get("leg_count")
                minimum = _coerce_float(expected)
                if minimum is None or actual is None or float(actual) < minimum:
                    return False
            elif key == "leg_count_max":
                actual = data.get("leg_count")
                maximum = _coerce_float(expected)
                if maximum is None or actual is None or float(actual) > maximum:
                    return False
            elif key == "underlying_min":
                minimum = _coerce_float(expected)
                if minimum is None or underlying is None or float(underlying) < minimum:
                    return False
            elif key == "underlying_max":
                maximum = _coerce_float(expected)
                if maximum is None or underlying is None or float(underlying) > maximum:
                    return False
            elif key == "mid_min":
                minimum = _coerce_float(expected)
                if minimum is None or mid is None or float(mid) < minimum:
                    return False
            elif key == "mid_max":
                maximum = _coerce_float(expected)
                if maximum is None or mid is None or float(mid) > maximum:
                    return False
            elif key == "width_min":
                minimum = _coerce_float(expected)
                if minimum is None or spread is None or float(spread) < minimum:
                    return False
            elif key == "width_max":
                maximum = _coerce_float(expected)
                if maximum is None or spread is None or float(spread) > maximum:
                    return False
        return True


def _match_text(candidate: Any, expected: Any) -> bool:
    options = {
        str(item).strip().lower()
        for item in _as_sequence(expected)
        if str(item).strip()
    }
    if not options:
        return False
    value = str(candidate or "").strip().lower()
    return value in options


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SpreadPolicy:
    """Evaluate bid/ask spreads for complex option structures."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        default_relative: float | None = None,
        default_absolute: Sequence[Mapping[str, Any]] | None = None,
        default_exceptions: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._rule_default = self._build_rule(
            name="default",
            config=self._config,
            fallback_relative=default_relative,
            fallback_absolute=default_absolute,
        )
        exceptions = self._config.get("exceptions")
        if exceptions is None:
            exceptions = default_exceptions or []
        self._exceptions: list[_ExceptionRule] = []
        for idx, data in enumerate(_as_sequence(exceptions)):
            if not isinstance(data, Mapping):
                continue
            name = str(data.get("name") or f"exception_{idx}")
            rule = self._build_rule(
                name=name,
                config=data,
                fallback_relative=self._rule_default.relative_factor,
                fallback_absolute=self._config.get("absolute"),
            )
            match = data.get("match") or data.get("when")
            if isinstance(match, Mapping):
                self._exceptions.append(
                    _ExceptionRule(name=name, match=match, rule=rule)
                )

    def _build_rule(
        self,
        *,
        name: str,
        config: Mapping[str, Any],
        fallback_relative: float | None,
        fallback_absolute: Sequence[Mapping[str, Any]] | float | None,
    ) -> _SpreadRule:
        relative = config.get("relative")
        rel_value = _coerce_float(relative)
        if rel_value is None:
            rel_value = fallback_relative

        raw_absolute = config.get("absolute")
        absolute_value: float | None = None
        buckets: Sequence[_SpreadBucket] = ()
        if isinstance(raw_absolute, (int, float, str)):
            absolute_value = _coerce_float(raw_absolute)
        elif isinstance(raw_absolute, Iterable):
            buckets = tuple(
                bucket
                for item in raw_absolute
                if isinstance(item, Mapping)
                for bucket in (_SpreadBucket.from_mapping(item),)
                if bucket is not None
            )
        elif isinstance(fallback_absolute, Iterable):
            buckets = tuple(
                bucket
                for item in fallback_absolute
                if isinstance(item, Mapping)
                for bucket in (_SpreadBucket.from_mapping(item),)
                if bucket is not None
            )
        elif isinstance(fallback_absolute, (int, float, str)):
            absolute_value = _coerce_float(fallback_absolute)

        return _SpreadRule(
            name=name,
            relative=rel_value,
            absolute=absolute_value,
            buckets=buckets,
        )

    def evaluate(
        self,
        *,
        spread: float,
        mid: float | None,
        underlying: float | None = None,
        context: Mapping[str, Any] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> SpreadDecision:
        rule = self._select_rule(context=context, mid=mid, underlying=underlying, spread=spread)
        reason = "too_wide"
        if mid is None or mid <= 0:
            return SpreadDecision(False, "invalid_mid", None, None, None, rule.name)

        abs_threshold = rule.absolute_threshold(underlying)
        rel_threshold = rule.relative_threshold(mid)

        if overrides:
            abs_override = _coerce_float(overrides.get("absolute"))
            if abs_override is not None:
                abs_threshold = max(0.0, abs_override)
            rel_override = _coerce_float(overrides.get("relative"))
            if rel_override is not None:
                rel_threshold = max(0.0, rel_override) * float(mid)

        candidates = [value for value in (abs_threshold, rel_threshold) if value is not None]
        threshold = max(candidates) if candidates else None

        if abs_threshold is not None and spread <= abs_threshold + 1e-9:
            reason = "abs"
            threshold = abs_threshold
            return SpreadDecision(True, reason, threshold, abs_threshold, rel_threshold, rule.name)
        if rel_threshold is not None and spread <= rel_threshold + 1e-9:
            reason = "rel"
            threshold = rel_threshold
            return SpreadDecision(True, reason, threshold, abs_threshold, rel_threshold, rule.name)
        if threshold is None:
            # No thresholds → accept
            return SpreadDecision(True, "unbounded", None, None, None, rule.name)
        return SpreadDecision(False, reason, threshold, abs_threshold, rel_threshold, rule.name)

    def _select_rule(
        self,
        *,
        context: Mapping[str, Any] | None,
        mid: float | None,
        underlying: float | None,
        spread: float | None,
    ) -> _SpreadRule:
        for exception in self._exceptions:
            if exception.matches(context=context, mid=mid, underlying=underlying, spread=spread):
                return exception.rule
        return self._rule_default


__all__ = ["SpreadPolicy", "SpreadDecision"]

