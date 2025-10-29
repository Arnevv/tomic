from __future__ import annotations
from typing import Any, Dict, List
from . import StrategyName
from .utils import (
    MAX_PROPOSALS,
    ShortLegSpec,
    build_strategy_context,
    filter_expiries_by_dte,
    iter_short_candidates,
    reached_limit,
    resolve_delta_range,
)
from ..utils import build_leg
from ..analysis.scoring import calculate_score, passes_risk
from ..logutils import log_combo_evaluation
from ..strategy_candidates import (
    StrategyProposal,
)



def generate(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
) -> tuple[List[StrategyProposal], list[str]]:
    ctx = build_strategy_context(symbol, option_chain, config, spot, atr)
    expiries = ctx.expiries()
    if not expiries:
        return [], ["geen expiraties beschikbaar"]

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []

    short_spec = ShortLegSpec(option_type="P", delta_range_key="short_put_delta_range")
    delta_range = resolve_delta_range(ctx, short_spec)

    dte_range = ctx.rules.get("dte_range")
    expiries = filter_expiries_by_dte(expiries, dte_range)

    if not delta_range:
        rejected_reasons.append("ongeldige delta range")
    else:
        for expiry in expiries:
            candidates = list(
                iter_short_candidates(
                    ctx.prepared_chain,
                    option_type=short_spec.normalized_option_type,
                    expiries=[expiry],
                    delta_range=delta_range,
                )
            )
            for opt in candidates:
                desc = f"short {opt.get('strike')}"
                leg = build_leg({**opt, "spot": ctx.spot}, "short")
                proposal = StrategyProposal(strategy=str(StrategyName.NAKED_PUT), legs=[leg])
                score, reasons = calculate_score(
                    StrategyName.NAKED_PUT, proposal, ctx.spot, atr=ctx.atr
                )
                reason_messages = [detail.message for detail in reasons]
                if score is not None and passes_risk(proposal, ctx.min_rr):
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
                    reason = "; ".join(reason_messages) if reason_messages else "risk/reward onvoldoende"
                    log_combo_evaluation(
                        StrategyName.NAKED_PUT,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=[leg],
                    )
                    if reason_messages:
                        rejected_reasons.extend(reason_messages)
                    else:
                        rejected_reasons.append("risk/reward onvoldoende")
                if reached_limit(proposals):
                    break
            if reached_limit(proposals):
                break

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))
