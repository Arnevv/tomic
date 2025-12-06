from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple, TYPE_CHECKING
import math

from ..core.pricing.mid_tags import MidTagSnapshot
from ..metrics import (
    MidPriceResolver,
    calculate_credit,
    calculate_ev,
    calculate_pos,
    calculate_rom,
    estimate_scenario_profit,
    get_signed_position,
    iter_leg_views,
)
from ..pricing.margin_engine import compute_margin_and_rr
from ..criteria import CriteriaConfig, RULES, load_criteria
from ..helpers.numeric import safe_float
from ..utils import normalize_leg, get_leg_right
from ..logutils import logger
from ..mid_resolver import MidUsageSummary
from ..strategy.reasons import (
    ReasonCategory,
    ReasonDetail,
    dedupe_reasons,
    make_reason,
)
from ..strategy.reason_engine import ReasonEngine

# Import helpers and validators from extracted modules
from .scoring_helpers import (
    CREDIT_TO_WIDTH_WARN_RATIO,
    ROM_WARN_THRESHOLD,
    MARGIN_MIN_THRESHOLD,
    clamp,
    normalize_ratio,
    normalize_pos,
    normalize_risk_reward,
    resolve_strategy_config,
    resolve_min_risk_reward,
    max_credit_for_strategy,
    populate_additional_metrics,
    bs_estimate_missing,
)
from .scoring_validators import (
    validate_entry_quality,
    validate_leg_metrics,
    validate_exit_tradability,
    check_liquidity,
    fallback_limit_ok,
    preview_penalty,
)

if TYPE_CHECKING:
    from tomic.strategy_candidates import StrategyProposal

POSITIVE_CREDIT_STRATS = set(RULES.strategy.acceptance.require_positive_credit_for)

_REASON_ENGINE = ReasonEngine()

# Internal aliases for backward compatibility with underscore-prefixed names
_clamp = clamp
_normalize_ratio = normalize_ratio
_normalize_pos = normalize_pos
_normalize_risk_reward = normalize_risk_reward
_max_credit_for_strategy = max_credit_for_strategy
_resolve_strategy_config = resolve_strategy_config
_fallback_limit_ok = fallback_limit_ok
_preview_penalty = preview_penalty
_populate_additional_metrics = populate_additional_metrics
_bs_estimate_missing = bs_estimate_missing


def calculate_breakevens(
    strategy: str | Any, legs: List[Dict[str, Any]], credit: float
) -> Optional[List[float]]:
    """Return simple breakeven estimates for supported strategies.

    ``credit`` should be the net credit per contract. Breakevens are offset
    using the per-share value (``credit / 100``).
    """
    if not legs:
        return None
    strategy = getattr(strategy, "value", strategy)
    credit_ps = credit / 100.0
    if strategy in {"short_put_spread", "short_call_spread"}:
        short = [l for l in legs if get_signed_position(l) < 0][0]
        strike = float(short.get("strike"))
        if strategy == "short_put_spread":
            return [strike - credit_ps]
        return [strike + credit_ps]
    if strategy in {"iron_condor", "atm_iron_butterfly"}:
        short_put = [
            l for l in legs if get_signed_position(l) < 0 and get_leg_right(l) == "put"
        ]
        short_call = [
            l for l in legs if get_signed_position(l) < 0 and get_leg_right(l) == "call"
        ]
        if short_put and short_call:
            sp = float(short_put[0].get("strike"))
            sc = float(short_call[0].get("strike"))
            return [sp - credit_ps, sc + credit_ps]
    if strategy == "naked_put":
        short = legs[0]
        strike = float(short.get("strike"))
        return [strike - credit_ps]
    if strategy == "calendar":
        return [float(legs[0].get("strike"))]
    return None


# Note: The following functions are now imported from scoring_validators:
# - validate_entry_quality
# - validate_leg_metrics
# - validate_exit_tradability
# - check_liquidity
# - fallback_limit_ok
# - preview_penalty


def compute_proposal_metrics(
    strategy_name: str,
    proposal: "StrategyProposal",
    legs: List[Dict[str, Any]],
    crit: CriteriaConfig,
    spot: float | None = None,
    *,
    fallback_count: int = 0,
    fallback_allowed: int = 0,
    fallback_reason: str | None = None,
    fallback_warning: str | None = None,
) -> Tuple[Optional[float], List[ReasonDetail]]:
    """Compute proposal metrics and return score with structured reasons."""

    reasons: List[ReasonDetail] = []

    def _finalize(result_score: Optional[float]) -> Tuple[Optional[float], List[ReasonDetail]]:
        deduped = dedupe_reasons(reasons)
        proposal.reasons = deduped
        return result_score, deduped

    for leg in legs:
        normalize_leg(leg)

    short_deltas = [
        abs(leg.get("delta", 0))
        for leg in legs
        if get_signed_position(leg) < 0 and leg.get("delta") is not None
    ]
    proposal.pos = calculate_pos(sum(short_deltas) / len(short_deltas)) if short_deltas else None

    short_edges: List[float] = []
    for leg in legs:
        if get_signed_position(leg) < 0:
            try:
                edge_val = float(leg.get("edge"))
            except (TypeError, ValueError):
                edge_val = math.nan
            if not math.isnan(edge_val):
                short_edges.append(edge_val)
    proposal.edge = round(sum(short_edges) / len(short_edges), 2) if short_edges else None

    leg_views = list(iter_leg_views(legs, price_resolver=MidPriceResolver))

    missing_mid: List[str] = []
    for leg, view in zip(legs, leg_views):
        if view.mid is None:
            missing_mid.append(str(leg.get("strike")))

    if missing_mid:
        logger.info(
            f"[{strategy_name}] Ontbrekende bid/ask-data voor strikes {','.join(missing_mid)}"
        )
        reasons.append(
            make_reason(
                ReasonCategory.MISSING_DATA,
                "BID_ASK_MISSING",
                "ontbrekende bid/ask-data",
                data={"legs": list(missing_mid)},
            )
        )

    seen_codes: set[str] = {detail.code for detail in reasons}

    def _add_reason(detail: ReasonDetail | None) -> None:
        if detail is None:
            return
        if detail.code in seen_codes:
            return
        reasons.append(detail)
        seen_codes.add(detail.code)

    net_credit = calculate_credit(leg_views, price_resolver=None) / 100.0

    theoretical_cap = _max_credit_for_strategy(strategy_name, legs)
    credit_capped = False
    if theoretical_cap is not None and net_credit > theoretical_cap + 1e-6:
        logger.warning(
            "[%s] Credit %.2f boven theoretisch maximum %.2f – wordt afgetopt",
            strategy_name,
            net_credit,
            theoretical_cap,
        )
        net_credit = theoretical_cap
        credit_capped = True

    if strategy_name in POSITIVE_CREDIT_STRATS and net_credit <= 0:
        _add_reason(
            make_reason(
                ReasonCategory.POLICY_VIOLATION,
                "NEGATIVE_CREDIT",
                "negatieve credit",
            )
        )
        return _finalize(None)

    proposal.credit = net_credit * 100
    proposal.credit_capped = credit_capped
    proposal.profit_estimated = False
    proposal.scenario_info = None

    strategy_cfg = _resolve_strategy_config(strategy_name)
    min_rr_threshold = resolve_min_risk_reward(strategy_cfg, crit)
    engine_config = dict(strategy_cfg)
    engine_config["min_risk_reward"] = min_rr_threshold

    computation = compute_margin_and_rr(
        {
            "strategy": strategy_name,
            "legs": legs,
            "net_cashflow": net_credit,
        },
        config=engine_config,
    )
    margin = computation.margin
    proposal.max_profit = computation.max_profit
    proposal.max_loss = computation.max_loss
    proposal.risk_reward = computation.risk_reward

    if margin is None or (isinstance(margin, float) and math.isnan(margin)):
        _add_reason(
            make_reason(
                ReasonCategory.MISSING_DATA,
                "MARGIN_MISSING",
                "margin kon niet worden berekend",
            )
        )
        return _finalize(None)

    for leg in legs:
        leg["margin"] = margin
    proposal.margin = margin

    if strategy_name == "naked_put":
        proposal.max_profit = net_credit * 100
        proposal.max_loss = -margin
    elif strategy_name in {"ratio_spread", "backspread_put", "calendar"}:
        proposal.max_loss = -margin

    if ((proposal.max_profit is None or proposal.max_profit <= 0) or strategy_name == "ratio_spread") and spot is not None:
        scenarios, err = estimate_scenario_profit(legs, spot, strategy_name)
        if scenarios:
            preferred = next((s for s in scenarios if s.get("preferred_move")), scenarios[0])
            pnl = preferred.get("pnl")
            proposal.max_profit = abs(pnl) if pnl is not None else None
            proposal.scenario_info = preferred
            proposal.profit_estimated = True
            label = preferred.get("scenario_label")
            logger.info(f"[SCENARIO] {strategy_name}: profit estimate at {label} {proposal.max_profit}")
        else:
            proposal.scenario_info = {"error": err or "no scenario defined"}

    profit_val = safe_float(proposal.max_profit)
    loss_val = safe_float(proposal.max_loss)
    if proposal.risk_reward is None and profit_val is not None and loss_val not in (None, 0.0):
        risk = abs(loss_val)
        if risk > 0 and profit_val > 0:
            # R/R = max_loss / max_profit (TOMIC definition: risk per unit reward)
            # Lower is better. Threshold check: R/R <= min_rr
            proposal.risk_reward = risk / profit_val

    min_rr = computation.min_risk_reward or 0.0
    meets_min = bool(computation.meets_min_risk_reward)
    if not meets_min:
        message = (
            f"risk/reward onvoldoende ({proposal.risk_reward:.2f} > {min_rr:.2f})"
            if proposal.risk_reward is not None
            else f"risk/reward onvoldoende (> {min_rr:.2f})"
        )
        _add_reason(
            make_reason(
                ReasonCategory.RR_BELOW_MIN,
                "RR_TOO_LOW",
                message,
                data={
                    "risk_reward": round(proposal.risk_reward, 4) if proposal.risk_reward is not None else None,
                    "min_risk_reward": round(min_rr, 4),
                },
            )
        )
        logger.info(f"[❌ voorstel afgewezen] {strategy_name} — reason: risk/reward onvoldoende")
        return _finalize(None)

    proposal.rom = calculate_rom(proposal.max_profit, margin) if proposal.max_profit is not None and margin else None
    if proposal.rom is None:
        _add_reason(
            make_reason(
                ReasonCategory.MISSING_DATA,
                "ROM_MISSING",
                "ROM kon niet worden berekend omdat margin ontbreekt",
            )
        )
    proposal.ev = (
        calculate_ev(proposal.pos or 0.0, proposal.max_profit or 0.0, proposal.max_loss or 0.0)
        if proposal.pos is not None and proposal.max_profit is not None and proposal.max_loss is not None
        else None
    )
    proposal.ev_pct = (proposal.ev / margin) * 100 if proposal.ev is not None and margin else None

    if proposal.ev_pct is not None and proposal.ev_pct < 0 and not proposal.profit_estimated:
        _add_reason(
            make_reason(
                ReasonCategory.EV_BELOW_MIN,
                "EV_TOO_LOW",
                "negatieve EV",
            )
        )
        logger.info(f"[❌ voorstel afgewezen] {strategy_name} — reason: EV negatief")
        return _finalize(None)

    # Sanity checks for suspicious "too good to be true" metrics
    if strategy_name in {"iron_condor", "atm_iron_butterfly"}:
        # Check credit-to-wing-width ratio
        if theoretical_cap is not None and theoretical_cap > 0:
            credit_to_width_ratio = net_credit / theoretical_cap
            if credit_to_width_ratio > _CREDIT_TO_WIDTH_WARN_RATIO:
                _add_reason(
                    make_reason(
                        ReasonCategory.SUSPICIOUS_METRICS,
                        "CREDIT_TO_WIDTH_HIGH",
                        f"credit/breedte verhouding verdacht hoog ({credit_to_width_ratio:.1%})",
                        data={
                            "credit": round(net_credit, 4),
                            "wing_width": round(theoretical_cap, 4),
                            "ratio": round(credit_to_width_ratio, 4),
                            "threshold": _CREDIT_TO_WIDTH_WARN_RATIO,
                        },
                    )
                )
                logger.warning(
                    f"[⚠️ {strategy_name}] Credit-to-width ratio {credit_to_width_ratio:.1%} > "
                    f"{_CREDIT_TO_WIDTH_WARN_RATIO:.0%} threshold — may indicate data quality issue"
                )

        # Check for very low margin (near-zero risk)
        if margin is not None and margin < _MARGIN_MIN_THRESHOLD:
            _add_reason(
                make_reason(
                    ReasonCategory.SUSPICIOUS_METRICS,
                    "MARGIN_TOO_LOW",
                    f"margin verdacht laag (${margin:.2f})",
                    data={
                        "margin": round(margin, 2),
                        "threshold": _MARGIN_MIN_THRESHOLD,
                    },
                )
            )
            logger.warning(
                f"[⚠️ {strategy_name}] Margin ${margin:.2f} < ${_MARGIN_MIN_THRESHOLD:.2f} threshold — "
                f"near-zero risk is unrealistic"
            )

        # Check for extremely high ROM
        if proposal.rom is not None and proposal.rom > _ROM_WARN_THRESHOLD:
            _add_reason(
                make_reason(
                    ReasonCategory.SUSPICIOUS_METRICS,
                    "ROM_SUSPICIOUSLY_HIGH",
                    f"ROM verdacht hoog ({proposal.rom:.1f}%)",
                    data={
                        "rom": round(proposal.rom, 2),
                        "threshold": _ROM_WARN_THRESHOLD,
                        "max_profit": round(proposal.max_profit, 2) if proposal.max_profit else None,
                        "margin": round(margin, 2) if margin else None,
                    },
                )
            )
            logger.warning(
                f"[⚠️ {strategy_name}] ROM {proposal.rom:.1f}% > {_ROM_WARN_THRESHOLD:.0f}% threshold — "
                f"'too good to be true' scenario"
            )

    strat_cfg = crit.strategy
    proposal.rom_norm = _normalize_ratio(proposal.rom, strat_cfg.rom_cap_pct)
    proposal.pos_norm = _normalize_pos(proposal.pos, strat_cfg.pos_floor_pct, strat_cfg.pos_span_pct)
    proposal.ev_norm = _normalize_ratio(proposal.ev_pct, strat_cfg.ev_cap_pct)
    proposal.rr_norm = _normalize_risk_reward(proposal.risk_reward, crit)

    components: list[dict[str, Any]] = []
    total = 0.0
    entries = [
        ("rom", proposal.rom, proposal.rom_norm, float(strat_cfg.score_weight_rom)),
        ("pos", proposal.pos, proposal.pos_norm, float(strat_cfg.score_weight_pos)),
        ("ev", proposal.ev_pct, proposal.ev_norm, float(strat_cfg.score_weight_ev)),
        ("rr", proposal.risk_reward, proposal.rr_norm, float(strat_cfg.score_weight_rr)),
    ]
    for name, raw_value, normalized, weight in entries:
        normalized_val = 0.0 if normalized is None else float(normalized)
        contribution = normalized_val * weight
        total += contribution
        components.append(
            {
                "component": name,
                "raw": raw_value,
                "normalized": None if normalized is None else round(normalized_val, 4),
                "weight": weight,
                "contribution": round(contribution, 6),
            }
        )

    total = _clamp(total, 0.0, 1.0)
    proposal.score_breakdown = components
    proposal.score = round(total * 100.0, 2)

    proposal.breakevens = calculate_breakevens(strategy_name, legs, net_credit * 100)

    summary = MidUsageSummary.from_legs(legs, fallback_allowed=fallback_allowed)

    _, penalty_detail, needs_refresh = _preview_penalty(
        strategy_name,
        summary.fallback_summary,
        preview_sources=summary.preview_sources,
        short_preview_legs=summary.preview_short_legs,
        long_preview_legs=summary.preview_long_legs,
        total_legs=len(legs),
        fallback_count=fallback_count,
        fallback_allowed=fallback_allowed,
        fallback_reason=fallback_reason,
        fallback_warning=fallback_warning,
    )
    if penalty_detail:
        _add_reason(penalty_detail)
    proposal.needs_refresh = needs_refresh

    evaluation = _REASON_ENGINE.evaluate(
        summary,
        existing_reasons=reasons,
        needs_refresh=proposal.needs_refresh,
    )
    proposal.fallback_summary = dict(evaluation.fallback_summary)
    proposal.needs_refresh = evaluation.needs_refresh
    proposal.mid_status = evaluation.status
    proposal.mid_status_tags = evaluation.tags
    proposal.mid_tags = MidTagSnapshot(
        tags=evaluation.tags,
        counters=dict(evaluation.fallback_summary),
    )
    proposal.preview_sources = evaluation.preview_sources
    proposal.fallback_limit_exceeded = evaluation.fallback_limit_exceeded
    proposal.spread_rejects_n = summary.spread_too_wide_count
    if evaluation.preview_sources:
        proposal.fallback = ",".join(evaluation.preview_sources)
    else:
        proposal.fallback = None
    reasons = list(evaluation.reasons)

    labels = strat_cfg.score_labels
    score_val = proposal.score or 0.0
    if score_val >= labels.strong_min:
        proposal.score_label = "A"
    elif score_val >= labels.good_min:
        proposal.score_label = "B"
    elif score_val >= labels.borderline_min:
        proposal.score_label = "C"
    else:
        proposal.score_label = "D"
    return _finalize(proposal.score)


def calculate_score(
    strategy: str | Any,
    proposal: "StrategyProposal",
    spot: float | None = None,
    *,
    criteria: CriteriaConfig | None = None,
    atr: float | None = None,
) -> Tuple[Optional[float], List[ReasonDetail]]:
    """Populate proposal metrics and return the computed score."""

    if atr is not None:
        proposal.atr = atr

    legs = proposal.legs
    strategy_name = getattr(strategy, "value", strategy)
    _bs_estimate_missing(legs)

    fallback_ok, fallback_count, fallback_allowed, fallback_reason = _fallback_limit_ok(
        strategy_name, legs
    )
    fallback_warning: str | None = None
    if not fallback_ok:
        if fallback_reason:
            if fallback_allowed:
                fallback_warning = f"{fallback_reason} ({fallback_count}/{fallback_allowed} toegestaan)"
            else:
                fallback_warning = fallback_reason
        else:
            fallback_warning = f"te veel fallback-legs ({fallback_count}/{fallback_allowed} toegestaan)"
        logger.info(f"[{strategy_name}] {fallback_warning}")

    valid, reasons = validate_entry_quality(strategy_name, legs)
    if not valid:
        return None, reasons

    crit = criteria or load_criteria()
    ok, reasons = check_liquidity(strategy_name, legs, crit)
    if not ok:
        return None, reasons

    score, reasons = compute_proposal_metrics(
        strategy_name,
        proposal,
        legs,
        crit,
        spot,
        fallback_count=fallback_count,
        fallback_allowed=fallback_allowed,
        fallback_reason=fallback_reason,
        fallback_warning=fallback_warning,
    )
    _populate_additional_metrics(proposal, legs, spot)
    return score, reasons


def passes_risk(proposal: "StrategyProposal" | Mapping[str, Any], min_rr: float) -> bool:
    """Return True if proposal satisfies configured risk/reward."""
    threshold = safe_float(min_rr) or 0.0
    if threshold <= 0:
        return True
    strategy = None
    if isinstance(proposal, Mapping):
        strategy = proposal.get("strategy")
    if strategy is None:
        strategy = getattr(proposal, "strategy", None)
    combo = {
        "strategy": strategy,
        "legs": proposal.get("legs") if isinstance(proposal, Mapping) else getattr(proposal, "legs", []),
        "margin": proposal.get("margin") if isinstance(proposal, Mapping) else getattr(proposal, "margin", None),
        "max_profit": proposal.get("max_profit") if isinstance(proposal, Mapping) else getattr(proposal, "max_profit", None),
        "max_loss": proposal.get("max_loss") if isinstance(proposal, Mapping) else getattr(proposal, "max_loss", None),
        "risk_reward": proposal.get("risk_reward") if isinstance(proposal, Mapping) else getattr(proposal, "risk_reward", None),
        "credit": proposal.get("credit") if isinstance(proposal, Mapping) else getattr(proposal, "credit", None),
    }
    result = compute_margin_and_rr(combo, {"min_risk_reward": threshold})
    return bool(result.meets_min_risk_reward)


__all__ = [
    "calculate_score",
    "calculate_breakevens",
    "passes_risk",
    "resolve_min_risk_reward",
    "validate_entry_quality",
    "validate_exit_tradability",
    "validate_leg_metrics",
]
