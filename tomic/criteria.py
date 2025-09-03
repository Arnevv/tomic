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

import math
from typing import List

from pydantic import BaseModel, model_validator

from .strategies import StrategyName as StrategyNameEnum
from .core.config_models import ConfigBase

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

    require_positive_credit_for: List[StrategyNameEnum] = []
    min_risk_reward: float | None = None


class StrategyRules(BaseModel):
    """Weights for evaluating strategy attractiveness."""

    score_weight_rom: float
    score_weight_pos: float
    score_weight_ev: float
    acceptance: StrategyAcceptanceRules = StrategyAcceptanceRules()

    @model_validator(mode="after")
    def _validate_score_weights(self) -> "StrategyRules":
        """Ensure score weights sum to 1.0 within a small tolerance."""
        total = self.score_weight_rom + self.score_weight_pos + self.score_weight_ev
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError("score weights must sum to 1.0")
        return self


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


class VegaIVRRule(BaseModel):
    """Parameters for combined vega/IV rank alerts."""

    vega: float
    iv_rank_min: float | None = None
    iv_rank_max: float | None = None
    message: str


class IVHVBands(BaseModel):
    """Thresholds for IV vs HV spread alerts."""

    high: float
    low: float


class ROMBands(BaseModel):
    """Bands for return-on-margin alerts."""

    high_min: float
    mid_min: float
    low_max: float


class PnLThetaRules(BaseModel):
    """PnL driven alerts based on theta and premium."""

    take_profit_pct_of_premium: float
    reconsider_loss_abs: float


class RiskThresholds(BaseModel):
    """Collection of configurable risk alert thresholds."""

    delta_dollar_max_abs: float
    delta_dollar_min_abs: float
    vega_abs_alert: float
    vega_short_high_ivr: VegaIVRRule
    vega_long_low_ivr: VegaIVRRule
    iv_hv_bands: IVHVBands
    rom_bands: ROMBands
    theta_efficiency_bands: List[float]
    dte_close_threshold: int
    days_in_trade_close_threshold: int
    pnl_theta: PnLThetaRules


class AlertRules(BaseModel):
    """Settings for user facing alerts."""

    nearest_strike_tolerance_percent: float
    skew_threshold: float
    iv_hv_min_spread: float
    iv_rank_threshold: float
    entry_checks: List[Rule] = []
    risk_thresholds: RiskThresholds = RiskThresholds(
        delta_dollar_max_abs=0.0,
        delta_dollar_min_abs=0.0,
        vega_abs_alert=0.0,
        vega_short_high_ivr=VegaIVRRule(vega=0.0, message=""),
        vega_long_low_ivr=VegaIVRRule(vega=0.0, message=""),
        iv_hv_bands=IVHVBands(high=0.0, low=0.0),
        rom_bands=ROMBands(high_min=0.0, mid_min=0.0, low_max=0.0),
        theta_efficiency_bands=[0.0, 0.0, 0.0],
        dte_close_threshold=0,
        days_in_trade_close_threshold=0,
        pnl_theta=PnLThetaRules(
            take_profit_pct_of_premium=0.0, reconsider_loss_abs=0.0
        ),
    )


class RulesConfig(ConfigBase):
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
    "VegaIVRRule",
    "IVHVBands",
    "ROMBands",
    "PnLThetaRules",
    "RiskThresholds",
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
