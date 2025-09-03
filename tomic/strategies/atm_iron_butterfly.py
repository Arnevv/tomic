from __future__ import annotations
from typing import Any, Dict, List
import pandas as pd
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from .utils import compute_dynamic_width
from ..helpers.analysis.scoring import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
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

    centers = rules.get("center_strike_relative_to_spot", [0])
    sigma_mult = float(rules.get("wing_sigma_multiple", 1.0))
    dte_range = rules.get("dte_range")
    for expiry in expiries:
        if dte_range:
            dte = _dte(expiry)
            if dte is None or not (dte_range[0] <= dte <= dte_range[1]):
                continue
        for c_off in centers:
            center = spot + (c_off * atr if use_atr else c_off)
            center = _nearest_strike(strike_map, expiry, "C", center).matched
            desc_base = f"center {center}"  # even if None
            if center is None:
                reason = "center strike niet gevonden"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc_base,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry}],
                )
                rejected_reasons.append(reason)
                continue
            sc_opt = _find_option(option_chain, expiry, center, "C")
            sp_opt = _find_option(option_chain, expiry, center, "P")
            if not sc_opt or not sp_opt:
                reason = "short opties niet gevonden"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc_base,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry, "strike": center, "type": "C", "position": -1},
                          {"expiry": expiry, "strike": center, "type": "P", "position": -1}],
                )
                rejected_reasons.append(reason)
                continue
            width = compute_dynamic_width(sc_opt, spot=spot, sigma_multiple=sigma_mult)
            if width is None:
                reason = "breedte niet berekend"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc_base,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry, "strike": center, "type": "C", "position": -1},
                          {"expiry": expiry, "strike": center, "type": "P", "position": -1}],
                )
                rejected_reasons.append(reason)
                continue
            sc_strike = center
            sp_strike = center
            lc_strike = _nearest_strike(strike_map, expiry, "C", center + width).matched
            lp_strike = _nearest_strike(strike_map, expiry, "P", center - width).matched
            desc = f"center {center} sigma {sigma_mult}"  # width implied
            base_legs = [
                {"expiry": expiry, "strike": sc_strike, "type": "C", "position": -1},
                {"expiry": expiry, "strike": sp_strike, "type": "P", "position": -1},
                {"expiry": expiry, "strike": lc_strike, "type": "C", "position": 1},
                {"expiry": expiry, "strike": lp_strike, "type": "P", "position": 1},
            ]
            if not all([sc_strike, sp_strike, lc_strike, lp_strike]):
                reason = "ontbrekende strikes"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=base_legs,
                )
                rejected_reasons.append(reason)
                continue
            lc_opt = _find_option(option_chain, expiry, lc_strike, "C")
            lp_opt = _find_option(option_chain, expiry, lp_strike, "P")
            if not all([lc_opt, lp_opt]):
                reason = "opties niet gevonden"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=base_legs,
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
                StrategyName.ATM_IRON_BUTTERFLY, proposal, spot
            )
            if score is not None and passes_risk(proposal, min_rr):
                proposals.append(proposal)
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
                    desc,
                    proposal.__dict__,
                    "pass",
                    "criteria",
                    legs=legs,
                )
            else:
                reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                log_combo_evaluation(
                    StrategyName.ATM_IRON_BUTTERFLY,
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
            if len(proposals) >= 5:
                break
        if len(proposals) >= 5:
            break
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:5], sorted(set(rejected_reasons))
