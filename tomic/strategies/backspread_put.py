from __future__ import annotations
from typing import Any, Dict, List
from . import StrategyName
from .utils import compute_dynamic_width, prepare_option_chain
from ..helpers.analysis.scoring import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation
from ..utils import get_leg_right
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _validate_ratio,
    select_expiry_pairs,
)
from ..strike_selector import _dte


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
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    option_chain = prepare_option_chain(option_chain, spot)
    strike_map = _build_strike_map(option_chain)
    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    delta_range = rules.get("short_put_delta_range") or []
    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")
    min_gap = int(rules.get("expiry_gap_min_days", 0))
    dte_range = rules.get("dte_range")
    filtered_expiries = []
    for exp in expiries:
        if dte_range:
            dte = _dte(exp)
            if dte is None or not (dte_range[0] <= dte <= dte_range[1]):
                continue
        filtered_expiries.append(exp)
    pairs = select_expiry_pairs(filtered_expiries, min_gap)
    if len(delta_range) == 2 and (target_delta is not None or atr_mult is not None):
        for near, far in pairs[:3]:
            short_opt = None
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == near
                    and get_leg_right(opt) == "put"
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    short_opt = opt
                    break
            if not short_opt:
                reason = "short optie ontbreekt"
                desc = (
                    f"near {near} far {far} target_delta {target_delta}"
                    if target_delta is not None
                    else f"near {near} far {far} atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": near}],
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
                expiry=far,
                option_type="P",
            )
            if width is None:
                reason = "breedte niet berekend"
                desc = (
                    f"near {near} far {far} target_delta {target_delta}"
                    if target_delta is not None
                    else f"near {near} far {far} atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[
                        {"expiry": near, "strike": short_opt.get("strike"), "type": "P", "position": -1}
                    ],
                )
                rejected_reasons.append(reason)
                continue
            long_strike_target = float(short_opt.get("strike")) - width
            long_strike = _nearest_strike(strike_map, far, "P", long_strike_target)
            desc = (
                f"near {near} far {far} short {short_opt.get('strike')} long {long_strike.matched}"
            )
            legs_info = [
                {"expiry": near, "strike": short_opt.get("strike"), "type": "P", "position": -1},
                {"expiry": far, "strike": long_strike.matched, "type": "P", "position": 2},
            ]
            if not long_strike.matched:
                reason = "long strike niet gevonden"
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=legs_info,
                )
                rejected_reasons.append(reason)
                continue
            long_opt = _find_option(option_chain, far, long_strike.matched, "P")
            if not long_opt:
                reason = "long optie ontbreekt"
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
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
                StrategyName.BACKSPREAD_PUT, proposal, spot
            )
            if score is not None and passes_risk(proposal, min_rr):
                if _validate_ratio(
                    "backspread_put", legs, proposal.credit or 0.0
                ):
                    proposals.append(proposal)
                    log_combo_evaluation(
                        StrategyName.BACKSPREAD_PUT,
                        desc,
                        proposal.__dict__,
                        "pass",
                        "criteria",
                        legs=legs,
                    )
                else:
                    reason = "verkeerde ratio"
                    log_combo_evaluation(
                        StrategyName.BACKSPREAD_PUT,
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
                    StrategyName.BACKSPREAD_PUT,
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
    else:
        rejected_reasons.append("ongeldige delta range")
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:5], sorted(set(rejected_reasons))
