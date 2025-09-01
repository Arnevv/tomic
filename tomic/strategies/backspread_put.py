from __future__ import annotations
from typing import Any, Dict, List
import pandas as pd
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from . import StrategyName
from .utils import compute_dynamic_width, make_leg, passes_risk
from ..logutils import log_combo_evaluation
from ..strategy_candidates import (
    StrategyProposal,
    _build_strike_map,
    _nearest_strike,
    _find_option,
    _metrics,
    _validate_ratio,
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

    delta_range = rules.get("short_put_delta_range") or []
    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")
    min_gap = int(rules.get("expiry_gap_min_days", 0))
    pairs = select_expiry_pairs(expiries, min_gap)
    if len(delta_range) == 2 and (target_delta is not None or atr_mult is not None):
        for near, far in pairs[:3]:
            short_opt = None
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == near
                    and (opt.get("type") or opt.get("right")) == "P"
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
                )
                rejected_reasons.append(reason)
                continue
            long_strike_target = float(short_opt.get("strike")) - width
            long_strike = _nearest_strike(strike_map, far, "P", long_strike_target)
            desc = (
                f"near {near} far {far} short {short_opt.get('strike')} long {long_strike.matched}"
            )
            if not long_strike.matched:
                reason = "long strike niet gevonden"
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    None,
                    "reject",
                    reason,
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
                )
                rejected_reasons.append(reason)
                continue
            legs = [
                make_leg(short_opt, -1, spot=spot),
                make_leg(long_opt, 2, spot=spot),
            ]
            if any(l is None for l in legs):
                reason = "leg data ontbreekt"
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    None,
                    "reject",
                    reason,
                )
                rejected_reasons.append(reason)
                continue
            metrics, reasons = _metrics(StrategyName.BACKSPREAD_PUT, legs, spot)
            if metrics and passes_risk(metrics, min_rr):
                if _validate_ratio("backspread_put", legs, metrics.get("credit", 0.0)):
                    proposals.append(StrategyProposal(legs=legs, **metrics))
                    log_combo_evaluation(
                        StrategyName.BACKSPREAD_PUT,
                        desc,
                        metrics,
                        "pass",
                        "criteria",
                    )
                else:
                    reason = "verkeerde ratio"
                    log_combo_evaluation(
                        StrategyName.BACKSPREAD_PUT,
                        desc,
                        metrics,
                        "reject",
                        reason,
                    )
                    rejected_reasons.append(reason)
            else:
                reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                log_combo_evaluation(
                    StrategyName.BACKSPREAD_PUT,
                    desc,
                    metrics,
                    "reject",
                    reason,
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
