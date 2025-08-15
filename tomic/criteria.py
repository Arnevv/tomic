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


class StrategyRules(BaseModel):
    """Weights for evaluating strategy attractiveness."""

    score_weight_rom: float
    score_weight_pos: float
    score_weight_ev: float


class MarketDataRules(BaseModel):
    """Minimum liquidity requirements for option data."""

    min_option_volume: int
    min_option_open_interest: int


class Rule(BaseModel):
    """Declarative rule definition for alerts/proposals."""

    condition: str
    message: str


class AlertRules(BaseModel):
    """Settings for user facing alerts."""

    nearest_strike_tolerance_percent: float
    entry_checks: List[Rule] = []


class RulesConfig(BaseModel):
    """Root configuration object combining all rule sections."""

    strike: StrikeRules
    strategy: StrategyRules
    market_data: MarketDataRules
    alerts: AlertRules


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
load_criteria = load_rules


__all__ = [
    "StrikeRules",
    "StrategyRules",
    "MarketDataRules",
    "Rule",
    "AlertRules",
    "RulesConfig",
    "RULES",
    # Backwards compatibility
    "StrikeCriteria",
    "StrategyCriteria",
    "MarketDataCriteria",
    "AlertCriteria",
    "CriteriaConfig",
    "load_rules",
    "load_criteria",
]
