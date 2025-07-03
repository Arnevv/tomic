from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .metrics import (
    calculate_margin,
    calculate_pos,
    calculate_rom,
    calculate_ev,
)
from .analysis.strategy import heuristic_risk_metrics, parse_date
from .utils import get_option_mid_price
from .logutils import logger
from .config import get as cfg_get


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


def select_expiry_pairs(expiries: List[str], min_gap: int) -> List[tuple[str, str]]:
    """Return pairs of expiries separated by at least ``min_gap`` days."""
    parsed = []
    for exp in expiries:
        d = parse_date(str(exp))
        if d:
            parsed.append((exp, d))
    parsed.sort(key=lambda t: t[1])
    pairs: List[tuple[str, str]] = []
    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            if (parsed[j][1] - parsed[i][1]).days >= min_gap:
                pairs.append((parsed[i][0], parsed[j][0]))
    return pairs


def _breakevens(strategy: str, legs: List[Dict[str, Any]], credit: float) -> Optional[List[float]]:
    """Return simple breakeven estimates for supported strategies."""
    if not legs:
        return None
    if strategy in {"bull put spread", "bear call spread"}:
        short = [l for l in legs if l.get("position") < 0][0]
        strike = float(short.get("strike"))
        if strategy == "bull put spread":
            return [strike - credit]
        return [strike + credit]
    if strategy in {"iron_condor", "atm_iron_butterfly"}:
        short_put = [l for l in legs if l.get("position") < 0 and (l.get("type") or l.get("right")) == "P"]
        short_call = [l for l in legs if l.get("position") < 0 and (l.get("type") or l.get("right")) == "C"]
        if short_put and short_call:
            sp = float(short_put[0].get("strike"))
            sc = float(short_call[0].get("strike"))
            return [sp - credit, sc + credit]
    if strategy == "naked_put":
        short = legs[0]
        strike = float(short.get("strike"))
        return [strike - credit]
    if strategy == "calendar":
        return [float(legs[0].get("strike"))]
    return None


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
    *,
    strategy: str = "",
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
    if strategy:
        logger.info(f"[{strategy}] Strike {strike}{right} {expiry} niet gevonden")
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
    rom_w = float(cfg_get("SCORE_WEIGHT_ROM", 0.5))
    pos_w = float(cfg_get("SCORE_WEIGHT_POS", 0.3))
    ev_w = float(cfg_get("SCORE_WEIGHT_EV", 0.2))

    score = 0.0
    if rom is not None:
        score += rom * rom_w
    if pos_val is not None:
        score += pos_val * pos_w
    if ev is not None:
        score += ev * ev_w

    breakevens = _breakevens(strategy, legs, credit * 100)

    return {
        "pos": pos_val,
        "ev": ev,
        "rom": rom,
        "credit": credit * 100,
        "margin": margin,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "breakevens": breakevens,
        "score": round(score, 2),
    }


def _validate_ratio(strategy: str, legs: List[Dict[str, Any]], credit: float) -> bool:
    shorts = [l for l in legs if l.get("position", 0) < 0]
    longs = [l for l in legs if l.get("position", 0) > 0]
    if not (len(shorts) == 1 and len(longs) == 2):
        logger.info(
            f"[{strategy}] Verhouding klopt niet: gevonden {len(shorts)} short en {len(longs)} long"
        )
        return False
    if credit <= 0:
        logger.info(f"[{strategy}] Credit niet positief: {credit}")
        return False
    short_strike = float(shorts[0].get("strike", 0))
    long_strikes = [float(l.get("strike", 0)) for l in longs]
    if strategy == "ratio_spread" and not all(ls > short_strike for ls in long_strikes):
        logger.info(f"[{strategy}] Long strikes niet hoger dan short strike")
        return False
    if strategy == "backspread_put" and not all(ls < short_strike for ls in long_strikes):
        logger.info(f"[{strategy}] Long strikes niet lager dan short strike")
        return False
    return True


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
            sc_opt = _find_option(option_chain, expiry, sc, "C", strategy=strategy_type)
            sp_opt = _find_option(option_chain, expiry, sp, "P", strategy=strategy_type)
            lc_opt = _find_option(option_chain, expiry, lc, "C", strategy=strategy_type)
            lp_opt = _find_option(option_chain, expiry, lp, "P", strategy=strategy_type)
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
                long_opt = _find_option(option_chain, expiry, long_strike, "P", strategy=strategy_type)
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
                long_opt = _find_option(option_chain, expiry, long_strike, "C", strategy=strategy_type)
                if not long_opt:
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics = _metrics("bear call spread", legs)
                proposals.append(StrategyProposal(legs=legs, **metrics))

    elif strategy_type == "naked_put":
        delta_range = rules.get("short_put_delta_range", [])
        if len(delta_range) == 2:
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == expiry
                    and (opt.get("type") or opt.get("right")) == "P"
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    leg = make_leg(opt, -1)
                    metrics = _metrics("naked_put", [leg])
                    proposals.append(StrategyProposal(legs=[leg], **metrics))
                    if len(proposals) >= 5:
                        break

    elif strategy_type == "calendar":
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        pairs = select_expiry_pairs(expiries, min_gap)
        strikes = rules.get("base_strikes_relative_to_spot", [])
        for near, far in pairs[:3]:
            for off in strikes:
                strike = spot + (off * atr if use_atr else off)
                short_opt = _find_option(option_chain, near, strike, "C", strategy=strategy_type)
                long_opt = _find_option(option_chain, far, strike, "C", strategy=strategy_type)
                if not short_opt or not long_opt:
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
                metrics = _metrics("calendar", legs)
                proposals.append(StrategyProposal(legs=legs, **metrics))
                if len(proposals) >= 5:
                    break

    elif strategy_type == "atm_iron_butterfly":
        centers = rules.get("center_strike_relative_to_spot", [0])
        widths = rules.get("wing_width_points", [])
        for c_off in centers:
            center = spot + (c_off * atr if use_atr else c_off)
            for width in widths:
                sc_opt = _find_option(option_chain, expiry, center, "C", strategy=strategy_type)
                sp_opt = _find_option(option_chain, expiry, center, "P", strategy=strategy_type)
                lc_opt = _find_option(option_chain, expiry, center + width, "C", strategy=strategy_type)
                lp_opt = _find_option(option_chain, expiry, center - width, "P", strategy=strategy_type)
                if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
                    continue
                legs = [
                    make_leg(sc_opt, -1),
                    make_leg(lc_opt, 1),
                    make_leg(sp_opt, -1),
                    make_leg(lp_opt, 1),
                ]
                metrics = _metrics("atm_iron_butterfly", legs)
                proposals.append(StrategyProposal(legs=legs, **metrics))
                if len(proposals) >= 5:
                    break

    elif strategy_type == "ratio_spread":
        delta_range = rules.get("short_leg_delta_range", [])
        widths = rules.get("long_leg_distance_points", [])
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
                long_opt = _find_option(option_chain, expiry, long_strike, "C", strategy=strategy_type)
                if not long_opt:
                    continue
                legs = [make_leg(short_opt, -1), make_leg(long_opt, 2)]
                metrics = _metrics("ratio_spread", legs)
                if _validate_ratio("ratio_spread", legs, metrics.get("credit", 0.0)):
                    proposals.append(StrategyProposal(legs=legs, **metrics))

    elif strategy_type == "backspread_put":
        delta_range = rules.get("short_put_delta_range", [])
        widths = rules.get("long_put_distance_points", [])
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        pairs = select_expiry_pairs(expiries, min_gap)
        if len(delta_range) == 2:
            for near, far in pairs[:3]:
                for width in widths:
                    short_opt = None
                    for opt in option_chain:
                        if (
                            str(opt.get("expiry")) == near
                            and (opt.get("type") or opt.get("right")) == "P"
                            and opt.get("delta") is not None
                            and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                        ):
                            short_opt = opt
                            break
                    if not short_opt:
                        continue
                    long_strike = float(short_opt.get("strike")) - width
                    long_opt = _find_option(option_chain, far, long_strike, "P", strategy=strategy_type)
                    if not long_opt:
                        continue
                    legs = [make_leg(short_opt, -1), make_leg(long_opt, 2)]
                    metrics = _metrics("backspread_put", legs)
                    if _validate_ratio("backspread_put", legs, metrics.get("credit", 0.0)):
                        proposals.append(StrategyProposal(legs=legs, **metrics))

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    return proposals[:5]


__all__ = [
    "StrategyProposal",
    "select_expiry_pairs",
    "generate_strategy_candidates",
]
