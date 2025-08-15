from __future__ import annotations
from typing import Any, Dict, List
import pandas as pd
from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from ..utils import get_option_mid_price, normalize_leg
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _metrics,
    _options_by_strike,
    select_expiry_pairs,
)


def generate(symbol: str, option_chain: List[Dict[str, Any]], config: Dict[str, Any], spot: float, atr: float) -> List[StrategyProposal]:
    strat_cfg = config.get("strategies", {}).get("calendar", {})
    rules = strat_cfg.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return []
    if spot is None:
        raise ValueError("spot price is required")
    expiry = expiries[0]
    strike_map = _build_strike_map(option_chain)
    if hasattr(pd, "DataFrame") and not isinstance(pd.DataFrame, type(object)):
        df_chain = pd.DataFrame(option_chain)
        if spot > 0:
            if "expiration" not in df_chain.columns and "expiry" in df_chain.columns:
                df_chain["expiration"] = df_chain["expiry"]
            df_chain = fill_missing_mid_with_parity(df_chain, spot=spot)
            option_chain = df_chain.to_dict(orient="records")
    proposals: List[StrategyProposal] = []
    min_rr = float(strat_cfg.get("min_risk_reward", 0.0))
    min_gap = int(rules.get("expiry_gap_min_days", 0))
    base_strikes = rules.get("base_strikes_relative_to_spot", [])
    by_strike = _options_by_strike(option_chain, "C")
    for off in base_strikes:
        strike_target = spot + (off * atr if use_atr else off)
        if not by_strike:
            continue
        avail = sorted(by_strike)
        nearest = min(avail, key=lambda s: abs(s - strike_target))
        diff = abs(nearest - strike_target)
        pct = (diff / strike_target * 100) if strike_target else 0.0
        if pct > 1.0:
            continue
        valid_exp = sorted(by_strike[nearest])
        pairs = select_expiry_pairs(valid_exp, min_gap)
        for near, far in pairs[:3]:
            short_opt = by_strike[nearest].get(near)
            long_opt = by_strike[nearest].get(far)
            if not short_opt or not long_opt:
                continue
            legs = [
                {
                    "expiry": short_opt.get("expiry"),
                    "type": short_opt.get("type"),
                    "strike": short_opt.get("strike"),
                    "delta": short_opt.get("delta"),
                    "bid": short_opt.get("bid"),
                    "ask": short_opt.get("ask"),
                    "mid": get_option_mid_price(short_opt),
                    "edge": short_opt.get("edge"),
                    "model": short_opt.get("model"),
                    "volume": short_opt.get("volume"),
                    "open_interest": short_opt.get("open_interest"),
                    "position": -1,
                },
                {
                    "expiry": long_opt.get("expiry"),
                    "type": long_opt.get("type"),
                    "strike": long_opt.get("strike"),
                    "delta": long_opt.get("delta"),
                    "bid": long_opt.get("bid"),
                    "ask": long_opt.get("ask"),
                    "mid": get_option_mid_price(long_opt),
                    "edge": long_opt.get("edge"),
                    "model": long_opt.get("model"),
                    "volume": long_opt.get("volume"),
                    "open_interest": long_opt.get("open_interest"),
                    "position": 1,
                },
            ]
            for leg in legs:
                if (
                    leg.get("edge") is None
                    and leg.get("mid") is not None
                    and leg.get("model") is not None
                ):
                    leg["edge"] = leg["model"] - leg["mid"]
            legs = [normalize_leg(l) for l in legs]
            metrics, _ = _metrics(StrategyName.CALENDAR, legs, spot)
            if not metrics:
                continue
            if min_rr > 0:
                mp = metrics.get("max_profit")
                ml = metrics.get("max_loss")
                if mp is not None and ml is not None and ml:
                    try:
                        rr = mp / abs(ml)
                    except Exception:
                        rr = None
                    if rr is not None and rr < min_rr:
                        continue
            proposals.append(StrategyProposal(legs=legs, **metrics))
            if len(proposals) >= 5:
                break
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    return proposals[:5]
