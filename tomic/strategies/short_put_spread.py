from __future__ import annotations
from typing import Any, Dict, List
import pandas as pd
from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from ..utils import get_option_mid_price, normalize_leg
from ..logutils import logger
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _metrics,
)


def generate(symbol: str, option_chain: List[Dict[str, Any]], config: Dict[str, Any], spot: float, atr: float) -> List[StrategyProposal]:
    strat_cfg = config.get("strategies", {}).get("short_put_spread", {})
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
        bid = opt.get("bid")
        ask = opt.get("ask")
        mid = get_option_mid_price(opt)
        used_close = False
        if mid is None:
            try:
                close_val = float(opt.get("close"))
                if close_val > 0:
                    mid = close_val
                    used_close = True
            except Exception:
                pass
        else:
            try:
                close_val = float(opt.get("close"))
                if mid == close_val:
                    used_close = True
            except Exception:
                pass
        if mid is None:
            return None
        leg = {
            "expiry": opt.get("expiry"),
            "type": opt.get("type") or opt.get("right"),
            "strike": opt.get("strike"),
            "spot": spot,
            "iv": opt.get("iv"),
            "delta": opt.get("delta"),
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "edge": opt.get("edge"),
            "model": opt.get("model"),
            "volume": opt.get("volume"),
            "open_interest": opt.get("open_interest"),
            "position": position,
        }
        def _missing(val: Any) -> bool:
            try:
                return float(val) <= 0
            except Exception:
                return True
        if opt.get("mid_from_parity"):
            leg["mid_fallback"] = "parity"
        elif used_close and (_missing(bid) or _missing(ask)):
            leg["mid_fallback"] = "close"
        try:
            opt_type = (opt.get("type") or opt.get("right") or "").upper()[0]
            strike = float(opt["strike"])
            iv = float(opt.get("iv"))
            exp = str(opt.get("expiry"))
            if spot and iv > 0.0 and exp:
                dte = dte_between_dates(today(), exp)
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
            long_strike_target = float(short_opt.get("strike")) - width
            long_strike = _nearest_strike(strike_map, expiry, "P", long_strike_target)
            logger.info(
                f"[short_put_spread] probeer short {short_opt.get('strike')} long {long_strike.matched}"
            )
            if not long_strike.matched:
                continue
            long_opt = _find_option(option_chain, expiry, long_strike.matched, "P")
            if not long_opt:
                continue
            legs = [make_leg(short_opt, -1), make_leg(long_opt, 1)]
            if any(l is None for l in legs):
                continue
            metrics, _ = _metrics(StrategyName.SHORT_PUT_SPREAD, legs, spot)
            if metrics and passes_risk(metrics):
                proposals.append(StrategyProposal(legs=legs, **metrics))
            if len(proposals) >= 5:
                break
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    return proposals[:5]
