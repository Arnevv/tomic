"""Centralized margin and risk/reward calculations for option strategies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, MutableMapping, Sequence

from ..strategies import StrategyName


class RiskModel(str, Enum):
    """Risk modelling approach applied to a strategy profile."""

    CREDIT = "credit"
    MARGIN_IS_RISK = "margin_is_risk"
    GENERIC = "generic"


@dataclass(frozen=True)
class StrategyProfile:
    """Configuration describing how to value a strategy."""

    name: str
    risk_model: RiskModel = RiskModel.GENERIC
    min_risk_reward: float | None = None
    require_margin: bool = True


@dataclass(frozen=True)
class MarginComputation:
    """Computed margin and risk characteristics for a combination."""

    strategy: str
    margin: float | None
    max_profit: float | None
    max_loss: float | None
    risk_reward: float | None
    min_risk_reward: float | None
    meets_min_risk_reward: bool | None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):  # pragma: no cover - defensive
            return float(value)
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_mapping(obj: Any) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return obj
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return None


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _coerce_strategy(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, StrategyName):
        return value.value
    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive
        return None


def _coerce_legs(obj: Any) -> list[dict[str, Any]]:
    legs: Sequence[Any] | None = None
    if isinstance(obj, Mapping):
        candidate = obj.get("legs")
        if isinstance(candidate, Sequence):
            legs = candidate
    if legs is None and hasattr(obj, "legs"):
        legs = getattr(obj, "legs")
    if legs is None:
        return []
    return [dict(leg) if isinstance(leg, MutableMapping) else dict(leg or {}) for leg in legs]  # type: ignore[arg-type]


def _infer_net_credit(obj: Any, legs: Sequence[Mapping[str, Any]]) -> float | None:
    for key in ("net_cashflow", "net_credit"):
        val = _safe_float(_get(obj, key))
        if val is not None:
            return val
    credit_total = _safe_float(_get(obj, "credit"))
    if credit_total is not None:
        return credit_total / 100.0
    debit_total = _safe_float(_get(obj, "debit"))
    if debit_total is not None:
        return -debit_total / 100.0
    try:
        from ..metrics import calculate_credit as _calculate_credit

        credit = _calculate_credit(list(legs))
    except Exception:
        return None
    return credit / 100.0


def _coerce_min_rr(value: float | None) -> float:
    """Return a non-negative risk/reward threshold for ``value``."""

    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(numeric) or numeric <= 0:
        return 0.0
    return numeric


def _merge_config(profile: StrategyProfile, config: Mapping[str, Any] | None) -> tuple[float, RiskModel]:
    min_rr = profile.min_risk_reward
    risk_model = profile.risk_model
    if config:
        cfg_min = _safe_float(config.get("min_risk_reward"))
        if cfg_min is not None:
            min_rr = cfg_min
        cfg_model = config.get("risk_model")
        if cfg_model is not None:
            try:
                risk_model = RiskModel(str(cfg_model))
            except ValueError:  # pragma: no cover - defensive
                pass
    return _coerce_min_rr(min_rr), risk_model


class MarginEngine:
    """Engine that standardizes margin and risk/reward calculations."""

    def __init__(self, profiles: Mapping[str, StrategyProfile] | None = None) -> None:
        if profiles is None:
            profiles = {
                StrategyName.SHORT_PUT_SPREAD.value: StrategyProfile(
                    StrategyName.SHORT_PUT_SPREAD.value,
                    risk_model=RiskModel.CREDIT,
                ),
                StrategyName.SHORT_CALL_SPREAD.value: StrategyProfile(
                    StrategyName.SHORT_CALL_SPREAD.value,
                    risk_model=RiskModel.CREDIT,
                ),
                StrategyName.IRON_CONDOR.value: StrategyProfile(
                    StrategyName.IRON_CONDOR.value,
                    risk_model=RiskModel.CREDIT,
                ),
                StrategyName.ATM_IRON_BUTTERFLY.value: StrategyProfile(
                    StrategyName.ATM_IRON_BUTTERFLY.value,
                    risk_model=RiskModel.CREDIT,
                ),
                StrategyName.NAKED_PUT.value: StrategyProfile(
                    StrategyName.NAKED_PUT.value,
                    risk_model=RiskModel.CREDIT,
                ),
                StrategyName.CALENDAR.value: StrategyProfile(
                    StrategyName.CALENDAR.value,
                    risk_model=RiskModel.MARGIN_IS_RISK,
                ),
                StrategyName.RATIO_SPREAD.value: StrategyProfile(
                    StrategyName.RATIO_SPREAD.value,
                    risk_model=RiskModel.MARGIN_IS_RISK,
                ),
                StrategyName.BACKSPREAD_PUT.value: StrategyProfile(
                    StrategyName.BACKSPREAD_PUT.value,
                    risk_model=RiskModel.MARGIN_IS_RISK,
                ),
            }
        self._profiles = {name: profile for name, profile in profiles.items()}

    def profile_for(self, strategy: str | None) -> StrategyProfile:
        if not strategy:
            return StrategyProfile(name="unknown", risk_model=RiskModel.GENERIC)
        profile = self._profiles.get(strategy.lower())
        if profile is None:
            return StrategyProfile(name=strategy.lower(), risk_model=RiskModel.GENERIC)
        return profile

    def compute_margin_and_rr(
        self,
        combination: Mapping[str, Any] | Any,
        config: Mapping[str, Any] | None = None,
    ) -> MarginComputation:
        """Return margin and risk metrics for ``combination``.

        The combination can be any mapping or object exposing ``strategy`` and
        ``legs`` attributes. Optional fields such as ``credit``, ``margin`` or
        ``risk_reward`` are used when available to avoid redundant
        computations.
        """

        strategy = _coerce_strategy(_get(combination, "strategy"))
        legs = _coerce_legs(combination)
        profile = self.profile_for(strategy)
        min_rr, risk_model = _merge_config(profile, config)

        net_credit = _infer_net_credit(combination, legs)

        margin = _safe_float(_get(combination, "margin"))
        if margin is None:
            try:
                from ..metrics import calculate_margin as _calculate_margin

                margin = _calculate_margin(strategy or "", legs, net_cashflow=net_credit or 0.0)
            except Exception:
                margin = None

        max_profit = _safe_float(_get(combination, "max_profit"))
        max_loss = _safe_float(_get(combination, "max_loss"))
        risk_reward = _safe_float(_get(combination, "risk_reward"))

        if (max_profit is None or max_loss is None or risk_reward is None) and legs:
            cost_basis = (-net_credit * 100) if net_credit is not None else None
            if cost_basis is not None:
                from ..analysis.strategy import heuristic_risk_metrics as _heuristic_risk_metrics

                metrics = _heuristic_risk_metrics(legs, cost_basis or 0.0)
            else:
                metrics = {}
            if max_profit is None:
                max_profit = _safe_float(metrics.get("max_profit"))
            if max_loss is None:
                max_loss = _safe_float(metrics.get("max_loss"))
            if risk_reward is None:
                risk_reward = _safe_float(metrics.get("risk_reward"))

        if risk_model == RiskModel.CREDIT:
            if net_credit is not None and net_credit > 0:
                max_profit = net_credit * 100
            if margin is not None:
                max_loss = -abs(margin)
        elif risk_model == RiskModel.MARGIN_IS_RISK:
            if margin is not None:
                max_loss = -abs(margin)

        if risk_reward is None and max_profit is not None and max_loss not in (None, 0.0):
            try:
                risk_reward = max_profit / abs(max_loss)
            except Exception:  # pragma: no cover - defensive
                risk_reward = None

        meets_min = True
        if min_rr > 0:
            if risk_reward is None:
                meets_min = False
            else:
                meets_min = risk_reward >= min_rr - 1e-9

        return MarginComputation(
            strategy=strategy or "unknown",
            margin=margin,
            max_profit=max_profit,
            max_loss=max_loss,
            risk_reward=risk_reward,
            min_risk_reward=min_rr,
            meets_min_risk_reward=meets_min,
        )


_DEFAULT_ENGINE = MarginEngine()


def compute_margin_and_rr(
    combination: Mapping[str, Any] | Any,
    config: Mapping[str, Any] | None = None,
) -> MarginComputation:
    """Proxy to the default :class:`MarginEngine` instance."""

    return _DEFAULT_ENGINE.compute_margin_and_rr(combination, config=config)


__all__ = [
    "MarginComputation",
    "MarginEngine",
    "RiskModel",
    "StrategyProfile",
    "compute_margin_and_rr",
]

