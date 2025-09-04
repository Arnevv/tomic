from __future__ import annotations
from typing import Any, Dict, List
from . import StrategyName
from .utils import prepare_option_chain
from ..helpers.analysis.scoring import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation
from ..utils import get_leg_right
from ..strategy_candidates import (
    StrategyProposal,
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
    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    delta_range = rules.get("short_put_delta_range") or []
    dte_range = rules.get("dte_range")
    if len(delta_range) == 2:
        for expiry in expiries:
            if dte_range:
                dte = _dte(expiry)
                if dte is None or not (dte_range[0] <= dte <= dte_range[1]):
                    continue
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == expiry
                    and get_leg_right(opt) == "put"
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    desc = f"short {opt.get('strike')}"
                    leg = build_leg({**opt, "spot": spot}, "short")
                    proposal = StrategyProposal(legs=[leg])
                    score, reasons = calculate_score(
                        StrategyName.NAKED_PUT, proposal, spot
                    )
                    if score is not None and passes_risk(proposal, min_rr):
                        proposals.append(proposal)
                        log_combo_evaluation(
                            StrategyName.NAKED_PUT,
                            desc,
                            proposal.__dict__,
                            "pass",
                            "criteria",
                            legs=[leg],
                        )
                    else:
                        reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                        log_combo_evaluation(
                            StrategyName.NAKED_PUT,
                            desc,
                            proposal.__dict__,
                            "reject",
                            reason,
                            legs=[leg],
                        )
                        if reasons:
                            rejected_reasons.extend(reasons)
                        else:
                            rejected_reasons.append("risk/reward onvoldoende")
                    if len(proposals) >= 5:
                        break
            if len(proposals) >= 5:
                break
    else:
        rejected_reasons.append("ongeldige delta range")
    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:5], sorted(set(rejected_reasons))
