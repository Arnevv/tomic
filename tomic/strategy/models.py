"""Shared dataclasses used across strategy subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .reasons import ReasonDetail


@dataclass
class StrategyContext:
    """Input parameters describing a single pipeline evaluation request."""

    symbol: str
    strategy: str
    option_chain: Sequence[MutableMapping[str, Any]]
    spot_price: float
    atr: float = 0.0
    config: Mapping[str, Any] | None = None
    interest_rate: float = 0.05
    dte_range: tuple[int, int] | None = None
    interactive_mode: bool = False
    criteria: Any | None = None
    next_earnings: date | None = None
    debug_path: Path | None = None


@dataclass
class StrategyProposal:
    """Standard representation of a generated option strategy."""

    strategy: str | None = None
    legs: list[dict[str, Any]] = field(default_factory=list)
    score: float | None = None
    pos: float | None = None
    ev: float | None = None
    ev_pct: float | None = None
    rom: float | None = None
    edge: float | None = None
    credit: float | None = None
    margin: float | None = None
    max_profit: float | None = None
    max_loss: float | None = None
    risk_reward: float | None = None
    breakevens: list[float] | None = None
    fallback: str | None = None
    profit_estimated: bool = False
    scenario_info: dict[str, Any] | None = None
    fallback_summary: dict[str, int] | None = None
    spread_rejects_n: int = 0
    atr: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    hv20: float | None = None
    hv30: float | None = None
    hv90: float | None = None
    dte: dict[str, Any] | None = None
    wing_width: dict[str, float] | None = None
    wing_symmetry: bool | None = None
    breakeven_distances: dict[str, list[float]] | None = None
    credit_capped: bool = False
    reasons: list[ReasonDetail] = field(default_factory=list)
    needs_refresh: bool = False


__all__ = ["StrategyContext", "StrategyProposal"]

