from __future__ import annotations

"""Structured criteria and rules configuration.

This module defines a small collection of :class:`pydantic.BaseModel`
classes which mirror the sections in ``criteria.yaml``.  The models are
loaded once at import time and exposed through :data:`RULES` so other
modules can simply import the ready-to-use configuration without worrying
about file parsing or validation.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from typing import List

from .config import _load_yaml  # reuse YAML loader


class StrikeRules(BaseModel):
    """Strike selection thresholds."""

    delta_min: float
    delta_max: float
    min_rom: float
    min_edge: float
    min_pos: float
    min_ev: float
    skew_min: float
    skew_max: float
    term_min: float
    term_max: float
    max_gamma: float | None = None
    max_vega: float | None = None
    min_theta: float | None = None


class StrategyAcceptanceRules(BaseModel):
    """Rules governing which strategies are acceptable."""

    require_positive_credit_for: List[str] = []


class StrategyRules(BaseModel):
    """Weights for evaluating strategy attractiveness."""

    score_weight_rom: float
    score_weight_pos: float
    score_weight_ev: float
    acceptance: StrategyAcceptanceRules = StrategyAcceptanceRules()


class MarketDataRules(BaseModel):
    """Minimum liquidity requirements for option data."""

    min_option_volume: int
    min_option_open_interest: int


class GateRules(BaseModel):
    """Thresholds for portfolio strategy suggestions."""

    iv_rank_min: float | None = None
    iv_rank_max: float | None = None
    iv_percentile_min: float | None = None
    iv_percentile_max: float | None = None
    vix_min: float | None = None
    vix_max: float | None = None
    term_m1_m3_min: float | None = None
    term_m1_m3_max: float | None = None


class PortfolioRules(BaseModel):
    """Portfolio level gating parameters."""

    vega_to_condor: float
    vega_to_calendar: float
    condor_gates: GateRules = GateRules()
    calendar_gates: GateRules = GateRules()


class Rule(BaseModel):
    """Declarative rule definition for alerts/proposals."""

    condition: str
    message: str


class AlertRules(BaseModel):
    """Settings for user facing alerts."""

    nearest_strike_tolerance_percent: float
    skew_threshold: float
    iv_hv_min_spread: float
    iv_rank_threshold: float
    entry_checks: List[Rule] = []


class RulesConfig(BaseModel):
    """Root configuration object combining all rule sections."""

    strike: StrikeRules
    strategy: StrategyRules
    market_data: MarketDataRules
    alerts: AlertRules
    portfolio: PortfolioRules


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_rules(path: str | Path | None = None) -> RulesConfig:
    """Load rules configuration from the YAML file once.

    Parameters
    ----------
    path:
        Optional path to the YAML file.  When omitted the default
        ``criteria.yaml`` located in the project root is used.
    """

    base = Path(__file__).resolve().parent.parent
    cfg_path = Path(path) if path else base / "criteria.yaml"
    data = _load_yaml(cfg_path) if cfg_path.exists() else {}
    return RulesConfig(**data)


# Load the configuration immediately so consuming modules can simply import
# :data:`RULES` from this module.
RULES: RulesConfig = load_rules()


# ---------------------------------------------------------------------------
# Backwards compatibility aliases
# ---------------------------------------------------------------------------

# Older code referenced the "Criteria" terminology.  Provide aliases so both
# the legacy and the new naming continue to work.
StrikeCriteria = StrikeRules
StrategyCriteria = StrategyRules
MarketDataCriteria = MarketDataRules
AlertCriteria = AlertRules
CriteriaConfig = RulesConfig
PortfolioCriteria = PortfolioRules
load_criteria = load_rules


__all__ = [
    "StrikeRules",
    "StrategyRules",
    "MarketDataRules",
    "StrategyAcceptanceRules",
    "GateRules",
    "PortfolioRules",
    "Rule",
    "AlertRules",
    "RulesConfig",
    "RULES",
    # Backwards compatibility
    "StrikeCriteria",
    "StrategyCriteria",
    "MarketDataCriteria",
    "AlertCriteria",
    "PortfolioCriteria",
    "CriteriaConfig",
    "load_rules",
    "load_criteria",
]
