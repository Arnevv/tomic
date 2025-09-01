from __future__ import annotations
from typing import Any, Dict, List

# Calendar strategy generator supporting calls and puts.
import pandas as pd
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from .utils import make_leg, passes_risk
from ..criteria import RULES
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _metrics,
    _options_by_strike,
    select_expiry_pairs,
)


def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List[StrategyProposal], list[str]]:
    rules = config.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
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
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))
    min_gap = int(rules.get("expiry_gap_min_days", 0))
    base_strikes = rules.get("base_strikes_relative_to_spot", [])

    preferred = str(config.get("preferred_option_type", "C")).upper()[0]
    order = [preferred] + (["P"] if preferred == "C" else ["C"])

    def _build_for(option_type: str) -> tuple[list[StrategyProposal], list[str]]:
        local_props: list[StrategyProposal] = []
        local_reasons: list[str] = []
        by_strike = _options_by_strike(option_chain, option_type)
        for off in base_strikes:
            strike_target = spot + (off * atr if use_atr else off)
            if not by_strike:
                local_reasons.append("geen strikes beschikbaar")
                continue
            avail = sorted(by_strike)
            candidate_strikes = sorted(avail, key=lambda s: abs(s - strike_target))
            nearest = None
            pairs: list = []
            for cand in candidate_strikes:
                valid_exp = sorted(by_strike[cand])
                pairs = select_expiry_pairs(valid_exp, min_gap)
                if not pairs:
                    local_reasons.append(
                        f"geen expiries beschikbaar voor strike {cand}"
                    )
                    continue
                diff = abs(cand - strike_target)
                pct = (diff / strike_target * 100) if strike_target else 0.0
                tol = float(RULES.alerts.nearest_strike_tolerance_percent)
                if pct > tol:
                    local_reasons.append("strike te ver van target")
                    continue
                nearest = cand
                break
            if not pairs or nearest is None:
                continue
            invalid_nears: set[str] = set()
            for near, far in pairs:
                if near in invalid_nears:
                    continue
                short_opt = by_strike[nearest].get(near)
                long_opt = by_strike[nearest].get(far)
                if not short_opt or not long_opt:
                    local_reasons.append("opties niet gevonden")
                    continue
                legs = [
                    make_leg(short_opt, -1, spot=spot),
                    make_leg(long_opt, 1, spot=spot),
                ]
                if any(l is None for l in legs):
                    local_reasons.append("leg data ontbreekt")
                    continue
                metrics, reasons = _metrics(StrategyName.CALENDAR, legs, spot)
                if not metrics:
                    if reasons:
                        local_reasons.extend(reasons)
                        if "onvoldoende volume/open interest" in reasons:
                            invalid_nears.add(near)
                    continue
                if not passes_risk(metrics, min_rr):
                    local_reasons.append("risk/reward onvoldoende")
                    continue
                local_props.append(StrategyProposal(legs=legs, **metrics))
                if len(local_props) >= 5:
                    break
        local_props.sort(key=lambda p: p.score or 0, reverse=True)
        return local_props, local_reasons

    for opt_type in order:
        props, reasons = _build_for(opt_type)
        rejected_reasons.extend(reasons)
        if props:
            proposals = props
            break
    else:
        proposals = []

    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:5], sorted(set(rejected_reasons))
