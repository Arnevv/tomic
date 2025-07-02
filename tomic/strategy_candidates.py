from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .metrics import (
    calculate_margin,
    calculate_pos,
    calculate_rom,
    calculate_ev,
)
from .analysis.strategy import heuristic_risk_metrics
from .utils import get_option_mid_price


@dataclass
class StrategyProposal:
    """Container for a generated option strategy."""

    legs: List[Dict[str, Any]] = field(default_factory=list)
    pos: Optional[float] = None
    ev: Optional[float] = None
    rom: Optional[float] = None
    edge: Optional[float] = None
    credit: Optional[float] = None
    margin: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakevens: Optional[List[float]] = None
    score: Optional[float] = None


def _spot_from_chain(chain: List[Dict[str, Any]]) -> Optional[float]:
    for opt in chain:
        for key in ("spot", "spot_price", "underlyingPrice", "Spot"):
            if opt.get(key) is not None:
                try:
                    return float(opt[key])
                except Exception:
                    continue
    return None


def _find_option(
    chain: List[Dict[str, Any]],
    expiry: str,
    strike: float,
    right: str,
) -> Optional[Dict[str, Any]]:
    for opt in chain:
        try:
            if (
                str(opt.get("expiry")) == str(expiry)
                and (opt.get("type") or opt.get("right")) == right
                and float(opt.get("strike")) == float(strike)
            ):
                return opt
        except Exception:
            continue
    return None


def _metrics(strategy: str, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    short_deltas = [
        abs(leg.get("delta", 0))
        for leg in legs
        if leg.get("position", 0) < 0 and leg.get("delta") is not None
    ]
    pos_val = calculate_pos(sum(short_deltas) / len(short_deltas)) if short_deltas else None

    credit = 0.0
    entry = 0.0
    for leg in legs:
        mid = leg.get("mid")
        if mid is None:
            continue
        if leg.get("position", 0) < 0:
            credit += mid
        else:
            entry += mid
    risk = heuristic_risk_metrics(legs, (entry - credit) * 100)
    margin = None
    try:
        margin = calculate_margin(strategy, legs, premium=credit, entry_price=entry)
    except Exception:
        margin = None

    max_profit = risk.get("max_profit")
    max_loss = risk.get("max_loss")
    rom = calculate_rom(max_profit, margin) if max_profit is not None and margin else None
    ev = (
        calculate_ev(pos_val or 0.0, max_profit or 0.0, max_loss or 0.0)
        if pos_val is not None and max_profit is not None and max_loss is not None
        else None
    )
    score = 0.0
    if rom is not None:
        score += rom * 0.5
    if pos_val is not None:
        score += pos_val * 0.3
    if ev is not None:
        score += ev * 0.2

    return {
        "pos": pos_val,
        "ev": ev,
        "rom": rom,
        "credit": credit * 100,
        "margin": margin,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "score": round(score, 2),
    }


def generate_strategy_candidates(
    symbol: str,
    strategy_type: str,
    option_chain: List[Dict[str, Any]],
    atr: float,
    config: Dict[str, Any],
) -> List[StrategyProposal]:
    """Return top strategy proposals for ``strategy_type``."""

    strat_cfg = config.get("strategies", {}).get(strategy_type, {})
    rules = strat_cfg.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    spot = _spot_from_chain(option_chain)
    if spot is None:
        return []

    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return []
    expiry = expiries[0]
    proposals: List[StrategyProposal] = []

    def make_leg(opt: Dict[str, Any], position: int) -> Dict[str, Any]:
        return {
            "expiry": opt.get("expiry"),
            "type": opt.get("type") or opt.get("right"),
            "strike": float(opt.get("strike")),
            "delta": opt.get("delta"),
            "bid": opt.get("bid"),
            "ask": opt.get("ask"),
            "mid": get_option_mid_price(opt),
            "position": position,
        }

    if strategy_type == "iron_condor":
        calls = rules.get("short_call_multiplier", [])
        puts = rules.get("short_put_multiplier", [])
        width = float(rules.get("wing_width", 0))
        for c_mult, p_mult in zip(calls, puts)[:5]:
            sc = spot + (c_mult * atr if use_atr else c_mult)
            sp = spot - (p_mult * atr if use_atr else p_mult)
            lc = sc + width
            lp = sp - width
            sc_opt = _find_option(option_chain, expiry, sc, "C")
            sp_opt = _find_option(option_chain, expiry, sp, "P")
            lc_opt = _find_option(option_chain, expiry, lc, "C")
            lp_opt = _find_option(option_chain, expiry, lp, "P")
            if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
                continue
            legs = [
                make_leg(sc_opt, -1),
                make_leg(lc_opt, 1),
                make_leg(sp_opt, -1),
                make_leg(lp_opt, 1),
            ]
            metrics = _metrics("iron_condor", legs)
            proposals.append(StrategyProposal(legs=legs, **metrics))

    elif strategy_type == "short_put_spread":
        delta_range = rules.get("short_put_delta_range", [])
        widths = rules.get("long_put_distance_points", [])
        if len(delta_range) == 2:
            for width in widths[:5]:
                short_opt = None
                for opt in option_chain:
                    if (
                        str(opt.get("expiry")) == expiry
                        and (opt.get("type") or opt.get("right")) == "P"
                        and opt.get("delta") is not None
                        and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                    ):
                        short_opt = opt
                        break
                if not short_opt:
                    continue
                long_strike = float(short_opt.get("strike")) - width
                long_opt = _find_option(option_chain, expiry, long_strike, "P")
                if not long_opt:
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics = _metrics("bull put spread", legs)
                proposals.append(StrategyProposal(legs=legs, **metrics))

    elif strategy_type == "short_call_spread":
        delta_range = rules.get("short_call_delta_range", [])
        widths = rules.get("long_call_distance_points", [])
        if len(delta_range) == 2:
            for width in widths[:5]:
                short_opt = None
                for opt in option_chain:
                    if (
                        str(opt.get("expiry")) == expiry
                        and (opt.get("type") or opt.get("right")) == "C"
                        and opt.get("delta") is not None
                        and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                    ):
                        short_opt = opt
                        break
                if not short_opt:
                    continue
                long_strike = float(short_opt.get("strike")) + width
                long_opt = _find_option(option_chain, expiry, long_strike, "C")
                if not long_opt:
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics = _metrics("bear call spread", legs)
                proposals.append(StrategyProposal(legs=legs, **metrics))

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    return proposals[:5]


__all__ = [
    "StrategyProposal",
    "generate_strategy_candidates",
]
