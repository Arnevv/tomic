from __future__ import annotations
from typing import Any, Dict, List
import math
from . import StrategyName
from .utils import (
    compute_dynamic_width,
    prepare_option_chain,
    filter_expiries_by_dte,
    MAX_PROPOSALS,
    reached_limit,
)
from ..helpers.analysis.scoring import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..utils import get_option_mid_price, get_leg_right
from ..logutils import log_combo_evaluation
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _validate_ratio,
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
    if spot is None:
        raise ValueError("spot price is required")
    option_chain = prepare_option_chain(option_chain, spot)
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    strike_map = _build_strike_map(option_chain)
    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    delta_range = rules.get("short_leg_delta_range") or []
    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")
    dte_range = rules.get("dte_range")
    expiries = filter_expiries_by_dte(expiries, dte_range)
    if len(delta_range) == 2 and (target_delta is not None or atr_mult is not None):
        for expiry in expiries:
            calls_pre = []
            for opt in option_chain:
                if str(opt.get("expiry")) != expiry:
                    rejected_reasons.append("verkeerde expiratie")
                    continue
                if get_leg_right(opt) != "call":
                    rejected_reasons.append("geen call optie")
                    continue
                delta = opt.get("delta")
                mid, _ = get_option_mid_price(opt)
                if delta is None or not (delta_range[0] <= float(delta) <= delta_range[1]):
                    rejected_reasons.append("delta buiten range")
                    continue
                try:
                    mid_val = float(mid) if mid is not None else math.nan
                except Exception:
                    mid_val = math.nan
                if math.isnan(mid_val):
                    rejected_reasons.append("mid ontbreekt")
                    continue
                calls_pre.append(opt)
            call_strikes = {float(o.get("strike")) for o in calls_pre}
            short_opt = None
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == expiry
                    and get_leg_right(opt) == "call"
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    short_opt = opt
                    break
            if not short_opt:
                reason = "short optie ontbreekt"
                desc = (
                    f"target_delta {target_delta}" if target_delta is not None else f"atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    StrategyName.RATIO_SPREAD,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry}],
                )
                rejected_reasons.append(reason)
                continue
            width = compute_dynamic_width(
                short_opt,
                target_delta=target_delta,
                atr_multiple=atr_mult,
                atr=atr,
                use_atr=use_atr,
                option_chain=option_chain,
                expiry=expiry,
                option_type="C",
            )
            if width is None:
                reason = "breedte niet berekend"
                desc = (
                    f"target_delta {target_delta}" if target_delta is not None else f"atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    StrategyName.RATIO_SPREAD,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[
                        {"expiry": expiry, "strike": short_opt.get("strike"), "type": "C", "position": -1}
                    ],
                )
                rejected_reasons.append(reason)
                continue
            long_strike_target = float(short_opt.get("strike")) + width
            long_strike = _nearest_strike(strike_map, expiry, "C", long_strike_target)
            desc = f"short {short_opt.get('strike')} long {long_strike.matched}"
            legs_info = [
                {"expiry": expiry, "strike": short_opt.get("strike"), "type": "C", "position": -1},
                {"expiry": expiry, "strike": long_strike.matched, "type": "C", "position": 2},
            ]
            if not long_strike.matched:
                reason = "long strike niet gevonden"
                log_combo_evaluation(
                    StrategyName.RATIO_SPREAD,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=legs_info,
                )
                rejected_reasons.append(reason)
                continue
            long_opt = _find_option(option_chain, expiry, long_strike.matched, "C")
            if not long_opt:
                reason = "long optie ontbreekt"
                log_combo_evaluation(
                    StrategyName.RATIO_SPREAD,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=legs_info,
                )
                rejected_reasons.append(reason)
                continue
            legs = [
                build_leg({**short_opt, "spot": spot}, "short"),
                build_leg({**long_opt, "spot": spot}, "long"),
            ]
            legs[1]["position"] = 2
            proposal = StrategyProposal(legs=legs)
            score, reasons = calculate_score(
                StrategyName.RATIO_SPREAD, proposal, spot
            )
            if score is not None and passes_risk(proposal, min_rr):
                if _validate_ratio("ratio_spread", legs, proposal.credit or 0.0):
                    proposals.append(proposal)
                    log_combo_evaluation(
                        StrategyName.RATIO_SPREAD,
                        desc,
                        proposal.__dict__,
                        "pass",
                        "criteria",
                        legs=legs,
                    )
                else:
                    reason = "verkeerde ratio"
                    log_combo_evaluation(
                        StrategyName.RATIO_SPREAD,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    rejected_reasons.append(reason)
            else:
                reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                log_combo_evaluation(
                    StrategyName.RATIO_SPREAD,
                    desc,
                    proposal.__dict__,
                    "reject",
                    reason,
                    legs=legs,
                )
                if reasons:
                    rejected_reasons.extend(reasons)
                else:
                    rejected_reasons.append("risk/reward onvoldoende")
            if reached_limit(proposals):
                break
    else:
        rejected_reasons.append("ongeldige delta range")
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))
