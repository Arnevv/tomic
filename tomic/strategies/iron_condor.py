from __future__ import annotations
from typing import Any, Dict, List
from itertools import islice
from . import StrategyName
from .utils import (
    compute_dynamic_width,
    prepare_option_chain,
    filter_expiries_by_dte,
    MAX_PROPOSALS,
)
from ..helpers.analysis.scoring import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation
from ..utils import get_leg_right
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
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
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    option_chain = prepare_option_chain(option_chain, spot)
    strike_map = _build_strike_map(option_chain)
    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    call_range = rules.get("short_call_delta_range") or []
    put_range = rules.get("short_put_delta_range") or []
    sigma_mult = float(rules.get("wing_sigma_multiple", 1.0))
    dte_range = rules.get("dte_range")
    expiries = filter_expiries_by_dte(expiries, dte_range)

    for expiry in expiries:
        shorts_c = [
            o
            for o in option_chain
            if str(o.get("expiry")) == expiry
            and get_leg_right(o) == "call"
            and o.get("delta") is not None
            and len(call_range) == 2
            and call_range[0] <= float(o["delta"]) <= call_range[1]
        ]
        shorts_p = [
            o
            for o in option_chain
            if str(o.get("expiry")) == expiry
            and get_leg_right(o) == "put"
            and o.get("delta") is not None
            and len(put_range) == 2
            and put_range[0] <= float(o["delta"]) <= put_range[1]
        ]
        if not shorts_c or not shorts_p:
            reason = "short optie ontbreekt"
            log_combo_evaluation(
                StrategyName.IRON_CONDOR,
                "delta scan",
                None,
                "reject",
                reason,
                legs=[{"expiry": expiry}],
            )
            rejected_reasons.append(reason)
            continue
        for sc_opt, sp_opt in islice(zip(shorts_c, shorts_p), MAX_PROPOSALS):
            sc_strike = float(sc_opt.get("strike"))
            sp_strike = float(sp_opt.get("strike"))
            sc = _nearest_strike(strike_map, expiry, "C", sc_strike)
            sp = _nearest_strike(strike_map, expiry, "P", sp_strike)
            desc = f"SC {sc.matched} SP {sp.matched} σ {sigma_mult}"
            base_legs = [
                {"expiry": expiry, "strike": sc_strike, "type": "C", "position": -1},
                {"expiry": expiry, "strike": sp_strike, "type": "P", "position": -1},
            ]
            if not sc.matched or not sp.matched:
                reason = "ontbrekende strikes"
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR, desc, None, "reject", reason, legs=base_legs
                )
                rejected_reasons.append(reason)
                continue
            c_w = compute_dynamic_width(sc_opt, spot=spot, sigma_multiple=sigma_mult)
            p_w = compute_dynamic_width(sp_opt, spot=spot, sigma_multiple=sigma_mult)
            if c_w is None or p_w is None:
                reason = "breedte niet berekend"
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR, desc, None, "reject", reason, legs=base_legs
                )
                rejected_reasons.append(reason)
                continue
            lc_target = sc_strike + c_w
            lp_target = sp_strike - p_w
            lc = _nearest_strike(strike_map, expiry, "C", lc_target)
            lp = _nearest_strike(strike_map, expiry, "P", lp_target)
            long_leg_info = [
                {"expiry": expiry, "strike": lc.matched, "type": "C", "position": 1},
                {"expiry": expiry, "strike": lp.matched, "type": "P", "position": 1},
            ]
            if not all([lc.matched, lp.matched]):
                reason = "ontbrekende strikes"
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=base_legs + long_leg_info,
                )
                rejected_reasons.append(reason)
                continue
            lc_opt = _find_option(option_chain, expiry, lc.matched, "C")
            lp_opt = _find_option(option_chain, expiry, lp.matched, "P")
            if not all([lc_opt, lp_opt]):
                reason = "opties niet gevonden"
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=base_legs + long_leg_info,
                )
                rejected_reasons.append(reason)
                continue
            legs = [
                build_leg({**sc_opt, "spot": spot}, "short"),
                build_leg({**lc_opt, "spot": spot}, "long"),
                build_leg({**sp_opt, "spot": spot}, "short"),
                build_leg({**lp_opt, "spot": spot}, "long"),
            ]
            proposal = StrategyProposal(legs=legs)
            score, reasons = calculate_score(
                StrategyName.IRON_CONDOR, proposal, spot
            )
            if score is not None and passes_risk(proposal, min_rr):
                proposals.append(proposal)
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR,
                    desc,
                    proposal.__dict__,
                    "pass",
                    "criteria",
                    legs=legs,
                )
            else:
                reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                log_combo_evaluation(
                    StrategyName.IRON_CONDOR,
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
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))
