from __future__ import annotations
from typing import Any, Dict, List

# Calendar strategy generator supporting calls and puts.
from . import StrategyName
from .utils import (
    prepare_option_chain,
    filter_expiries_by_dte,
    MAX_PROPOSALS,
    reached_limit,
)
from ..utils import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation, logger
from ..criteria import RULES
from ..strategy_candidates import (
    StrategyProposal,
    _find_option,
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
    option_chain = prepare_option_chain(option_chain, spot)

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))
    min_gap = int(rules.get("expiry_gap_min_days", 0))
    base_strikes = rules.get("base_strikes_relative_to_spot", [])
    dte_range = rules.get("dte_range")

    preferred = str(config.get("preferred_option_type", "C")).upper()[0]
    order = [preferred] + (["P"] if preferred == "C" else ["C"])

    logger.info("calendar: short parity ok, long fallback allowed (1)")

    def _build_for(option_type: str) -> tuple[list[StrategyProposal], list[str]]:
        local_props: list[StrategyProposal] = []
        local_reasons: list[str] = []
        by_strike = _options_by_strike(option_chain, option_type)
        for off in base_strikes:
            strike_target = spot + (off * atr if use_atr else off)
            desc_base = f"{option_type} target {strike_target}"
            if not by_strike:
                reason = "geen strikes beschikbaar"
                log_combo_evaluation(
                    StrategyName.CALENDAR, desc_base, None, "reject", reason
                )
                local_reasons.append(reason)
                continue
            avail = sorted(by_strike)
            candidate_strikes = sorted(avail, key=lambda s: abs(s - strike_target))
            nearest = None
            pairs: list = []
            for cand in candidate_strikes:
                valid_exp = sorted(by_strike[cand])
                if dte_range:
                    valid_exp = filter_expiries_by_dte(valid_exp, dte_range)
                pairs = select_expiry_pairs(valid_exp, min_gap)
                desc_cand = f"{option_type} strike {cand}"
                if not pairs:
                    reason = f"geen expiries beschikbaar voor strike {cand}"
                    log_combo_evaluation(
                        StrategyName.CALENDAR, desc_cand, None, "reject", reason
                    )
                    local_reasons.append(reason)
                    continue
                diff = abs(cand - strike_target)
                pct = (diff / strike_target * 100) if strike_target else 0.0
                tol = max(
                    float(RULES.alerts.nearest_strike_tolerance_percent),
                    5.0,
                )
                if pct > tol:
                    reason = "strike te ver van target"
                    log_combo_evaluation(
                        StrategyName.CALENDAR, desc_cand, None, "reject", reason
                    )
                    local_reasons.append(reason)
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
                desc = f"{option_type} strike {nearest} near {near} far {far}"
                legs_info = [
                    {"expiry": near, "strike": nearest, "type": option_type, "position": -1},
                    {"expiry": far, "strike": nearest, "type": option_type, "position": 1},
                ]
                if not short_opt or not long_opt:
                    reason = "opties niet gevonden"
                    log_combo_evaluation(
                        StrategyName.CALENDAR, desc, None, "reject", reason, legs=legs_info
                    )
                    local_reasons.append(reason)
                    continue
                legs = [
                    build_leg({**short_opt, "spot": spot}, "short"),
                    build_leg({**long_opt, "spot": spot}, "long"),
                ]
                proposal = StrategyProposal(legs=legs)
                score, reasons = calculate_score(
                    StrategyName.CALENDAR, proposal, spot
                )
                if score is None:
                    reason = "; ".join(reasons) if reasons else "metrics niet berekend"
                    log_combo_evaluation(
                        StrategyName.CALENDAR,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    if reasons:
                        local_reasons.extend(reasons)
                        if "onvoldoende volume/open interest" in reasons:
                            invalid_nears.add(near)
                    else:
                        local_reasons.append("metrics niet berekend")
                    continue
                if not passes_risk(proposal, min_rr):
                    reason = "risk/reward onvoldoende"
                    log_combo_evaluation(
                        StrategyName.CALENDAR,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    local_reasons.append(reason)
                    continue
                local_props.append(proposal)
                log_combo_evaluation(
                    StrategyName.CALENDAR,
                    desc,
                    proposal.__dict__,
                    "pass",
                    "criteria",
                    legs=legs,
                )
                if reached_limit(local_props):
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
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))
