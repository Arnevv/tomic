from __future__ import annotations
from typing import Any, Dict, List
import math
import pandas as pd
from itertools import islice
from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from .utils import validate_width_list
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
from .config_normalizer import normalize_config


def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List[StrategyProposal], list[str]]:
    rules = config.get("strike_to_strategy_config", {})
    normalize_config(
        rules, {"wing_width": ("wing_width_points", lambda v: v if isinstance(v, list) else [v])}
    )
    use_atr = bool(rules.get("use_ATR"))
    if spot is None:
        raise ValueError("spot price is required")
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
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
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    def make_leg(
        opt: Dict[str, Any], position: int
    ) -> tuple[Dict[str, Any] | None, str | None]:
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
            return None, "mid ontbreekt"
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
            expiry = str(opt.get("expiry"))
            if spot and iv > 0.0 and expiry:
                dte = dte_between_dates(today(), expiry)
                r = float(cfg_get("INTEREST_RATE", 0.05))
                q = 0.0  # evt. later per-symbool
                leg["model"] = black_scholes(opt_type, spot, strike, dte, iv, r=r, q=q)
        except Exception:
            pass
        if (
            leg.get("edge") is None
            and leg.get("mid") is not None
            and leg.get("model") is not None
        ):
            leg["edge"] = leg["model"] - leg["mid"]
        return normalize_leg(leg), None

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
    call_widths = rules.get("long_call_distance_points")
    put_widths = rules.get("long_put_distance_points")
    if call_widths is None or put_widths is None:
        legacy = rules.get("wing_width_points")
        if legacy is not None:
            if call_widths is None:
                call_widths = legacy
            if put_widths is None:
                put_widths = legacy

    call_widths = list(validate_width_list(call_widths, "long_call_distance_points"))
    put_widths = list(validate_width_list(put_widths, "long_put_distance_points"))
    for c_mult, p_mult, c_w, p_w in islice(
        zip(calls, puts, call_widths, put_widths), 5
    ):
        sc_target = spot + (c_mult * atr if use_atr else c_mult)
        sp_target = spot - (p_mult * atr if use_atr else p_mult)
        lc_target = sc_target + float(c_w)
        lp_target = sp_target - float(p_w)
        sc = _nearest_strike(strike_map, expiry, "C", sc_target)
        sp = _nearest_strike(strike_map, expiry, "P", sp_target)
        lc = _nearest_strike(strike_map, expiry, "C", lc_target)
        lp = _nearest_strike(strike_map, expiry, "P", lp_target)
        if not all([sc.matched, sp.matched, lc.matched, lp.matched]):
            rejected_reasons.append("ontbrekende strikes")
            continue
        sc_opt = _find_option(option_chain, expiry, sc.matched, "C")
        sp_opt = _find_option(option_chain, expiry, sp.matched, "P")
        lc_opt = _find_option(option_chain, expiry, lc.matched, "C")
        lp_opt = _find_option(option_chain, expiry, lp.matched, "P")
        if not all([sc_opt, sp_opt, lc_opt, lp_opt]):
            rejected_reasons.append("opties niet gevonden")
            continue
        sc_leg, sc_reason = make_leg(sc_opt, -1)
        lc_leg, lc_reason = make_leg(lc_opt, 1)
        sp_leg, sp_reason = make_leg(sp_opt, -1)
        lp_leg, lp_reason = make_leg(lp_opt, 1)
        legs = [sc_leg, lc_leg, sp_leg, lp_leg]
        leg_reasons = [sc_reason, lc_reason, sp_reason, lp_reason]
        if any(l is None for l in legs):
            rejected_reasons.append("leg data ontbreekt")
            rejected_reasons.extend(r for r in leg_reasons if r)
            continue
        metrics, reasons = _metrics(StrategyName.IRON_CONDOR, legs, spot)
        if metrics and passes_risk(metrics):
            proposals.append(StrategyProposal(legs=legs, **metrics))
        elif reasons:
            rejected_reasons.extend(reasons)
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:5], sorted(set(rejected_reasons))
