from __future__ import annotations
from typing import Any, Dict, List
import math
import pandas as pd
from itertools import islice
from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from ..utils import get_option_mid_price, normalize_leg, normalize_right
from ..logutils import logger
from ..config import get as cfg_get
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _metrics,
)


def generate(symbol: str, option_chain: List[Dict[str, Any]], config: Dict[str, Any], spot: float, atr: float) -> List[StrategyProposal]:
    strat_cfg = config.get("strategies", {}).get("iron_condor", {})
    rules = strat_cfg.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    if spot is None:
        raise ValueError("spot price is required")
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return []
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

    def make_leg(opt: Dict[str, Any], position: int) -> Dict[str, Any] | None:
        mid = get_option_mid_price(opt)
        if mid is None:
            try:
                close_val = float(opt.get("close"))
                if close_val > 0:
                    mid = close_val
            except Exception:
                pass
        if mid is None:
            return None
        leg = {
            "expiry": opt.get("expiry"),
            "type": opt.get("type") or opt.get("right"),
            "strike": opt.get("strike"),
            "delta": opt.get("delta"),
            "bid": opt.get("bid"),
            "ask": opt.get("ask"),
            "mid": mid,
            "edge": opt.get("edge"),
            "model": opt.get("model"),
            "volume": opt.get("volume"),
            "open_interest": opt.get("open_interest"),
            "position": position,
        }
        try:
            opt_type = (opt.get("type") or opt.get("right") or "").upper()[0]
            strike = float(opt["strike"])
            iv = float(opt.get("iv"))
            expiry = str(opt.get("expiry"))
            if spot and iv > 0.0 and expiry:
                dte = dte_between_dates(today(), expiry)
                leg["model"] = black_scholes(opt_type, spot, strike, dte, iv, r=0.045, q=0.0)
        except Exception:
            pass
        if (
            leg.get("edge") is None
            and leg.get("mid") is not None
            and leg.get("model") is not None
        ):
            leg["edge"] = leg["model"] - leg["mid"]
        return normalize_leg(leg)

    def passes_risk(metrics: Dict[str, Any]) -> bool:
        if not metrics or min_rr <= 0:
            return True
        mp = metrics.get("max_profit")
        ml = metrics.get("max_loss")
        if mp is None or ml is None or not ml:
            return True
        try:
            rr = mp / abs(ml)
        except Exception:
            return True
        return rr >= min_rr

    calls = rules.get("short_call_multiplier", [])
    puts = rules.get("short_put_multiplier", [])
    width = float(rules.get("wing_width", 0))
    for c_mult, p_mult in islice(zip(calls, puts), 5):
        sc_target = spot + (c_mult * atr if use_atr else c_mult)
        sp_target = spot - (p_mult * atr if use_atr else p_mult)
        lc_target = sc_target + width
        lp_target = sp_target - width
        sc = _nearest_strike(strike_map, expiry, "C", sc_target)
        sp = _nearest_strike(strike_map, expiry, "P", sp_target)
        lc = _nearest_strike(strike_map, expiry, "C", lc_target)
        lp = _nearest_strike(strike_map, expiry, "P", lp_target)
        if not all([sc.matched, sp.matched, lc.matched, lp.matched]):
            continue
        sc_opt = _find_option(option_chain, expiry, sc.matched, "C")
        sp_opt = _find_option(option_chain, expiry, sp.matched, "P")
        lc_opt = _find_option(option_chain, expiry, lc.matched, "C")
        lp_opt = _find_option(option_chain, expiry, lp.matched, "P")
        if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
            continue
        legs = [
            make_leg(sc_opt, -1),
            make_leg(lc_opt, 1),
            make_leg(sp_opt, -1),
            make_leg(lp_opt, 1),
        ]
        if any(l is None for l in legs):
            continue
        metrics, _ = _metrics("iron_condor", legs, spot)
        if metrics and passes_risk(metrics):
            proposals.append(StrategyProposal(legs=legs, **metrics))
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    return proposals[:5]
