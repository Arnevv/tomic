from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import _load_yaml  # reuse YAML loader


class StrikeCriteria(BaseModel):
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


class StrategyCriteria(BaseModel):
    score_weight_rom: float
    score_weight_pos: float
    score_weight_ev: float


class MarketDataCriteria(BaseModel):
    min_option_volume: int
    min_option_open_interest: int


class AlertCriteria(BaseModel):
    nearest_strike_tolerance_percent: float


class CriteriaConfig(BaseModel):
    strike: StrikeCriteria
    strategy: StrategyCriteria
    market_data: MarketDataCriteria
    alerts: AlertCriteria


@lru_cache(maxsize=1)
def load_criteria(path: str | Path | None = None) -> CriteriaConfig:
    """Load criteria configuration from YAML file once."""
    base = Path(__file__).resolve().parent.parent
    cfg_path = Path(path) if path else base / "criteria.yaml"
    data = _load_yaml(cfg_path) if cfg_path.exists() else {}
    return CriteriaConfig(**data)
