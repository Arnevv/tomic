from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple, TYPE_CHECKING
import math

from ..metrics import (
    calculate_margin,
    calculate_pos,
    calculate_rom,
    calculate_ev,
    estimate_scenario_profit,
)
from ..analysis.strategy import heuristic_risk_metrics
from ..criteria import CriteriaConfig, RULES, load_criteria
from ..utils import normalize_leg, get_leg_qty, get_leg_right
from ..logutils import logger
from ..config import get as cfg_get

if TYPE_CHECKING:
    from tomic.strategy_candidates import StrategyProposal

POSITIVE_CREDIT_STRATS = set(RULES.strategy.acceptance.require_positive_credit_for)


def _bs_estimate_missing(legs: List[Dict[str, Any]]) -> None:
    """Fill missing model price and delta using Black-Scholes."""
    from ..helpers.bs_utils import populate_model_delta

    for leg in legs:
        populate_model_delta(leg)


def _fallback_limit_ok(
    strategy_name: str, legs: List[Dict[str, Any]]
) -> tuple[bool, int, int, str | None]:
    limit_per_four = int(cfg_get("MID_FALLBACK_MAX_PER_4", 2) or 0)
    leg_count = len(legs)
    if leg_count == 0:
        return True, 0, 0, None
    if limit_per_four <= 0:
        allowed = 0
    else:
        allowed = math.ceil(limit_per_four * leg_count / 4)

    strat_label = getattr(strategy_name, "value", strategy_name)

    def _source(leg: Mapping[str, Any]) -> str:
        return str(leg.get("mid_source") or leg.get("mid_fallback") or "")

    def _is_short(leg: Mapping[str, Any]) -> bool:
        try:
            return float(leg.get("position") or 0) < 0
        except Exception:
            return False

    def _is_long(leg: Mapping[str, Any]) -> bool:
        try:
            return float(leg.get("position") or 0) > 0
        except Exception:
            return False

    fallback_sources = {"model", "close"}

    if strat_label in {
        "iron_condor",
        "atm_iron_butterfly",
        "ratio_spread",
        "backspread_put",
    }:
        allowed = min(allowed, 2) if allowed else 0
        long_fallbacks = sum(1 for leg in legs if _is_long(leg) and _source(leg) in fallback_sources)
        short_with_fallback = [leg for leg in legs if _is_short(leg) and _source(leg) in fallback_sources]
        if short_with_fallback:
            return False, long_fallbacks, allowed, "short legs vereisen true mid of parity"
        if long_fallbacks > allowed:
            reason = "te veel fallback-legs op long wings"
            return False, long_fallbacks, allowed, reason
        return True, long_fallbacks, allowed, None

    if strat_label in {"short_call_spread", "short_put_spread"}:
        allowed = min(allowed, 1) if allowed else 0
        long_fallbacks = sum(1 for leg in legs if _is_long(leg) and _source(leg) in fallback_sources)
        short_with_fallback = [leg for leg in legs if _is_short(leg) and _source(leg) in fallback_sources]
        if short_with_fallback:
            return False, long_fallbacks, allowed, "short legs vereisen true mid of parity"
        if long_fallbacks > allowed:
            reason = "te veel fallback-legs op long hedge"
            return False, long_fallbacks, allowed, reason
        return True, long_fallbacks, allowed, None

    if strat_label == "calendar":
        allowed = min(allowed, 1) if allowed else 0
        long_fallbacks = [leg for leg in legs if _is_long(leg) and _source(leg) in fallback_sources]
        if any(_is_short(leg) and _source(leg) in fallback_sources for leg in legs):
            return False, len(long_fallbacks), allowed, "short legs vereisen true mid of parity"
        if any(_source(leg) == "model" for leg in long_fallbacks):
            return False, len(long_fallbacks), allowed, "calendar long leg vereist parity of close"
        if len(long_fallbacks) > allowed:
            reason = "te veel fallback-legs op long hedge"
            return False, len(long_fallbacks), allowed, reason
        return True, len(long_fallbacks), allowed, None

    if strat_label == "naked_put":
        allowed = min(allowed, 1) if allowed else 0
        count = 0
        for leg in legs:
            if _source(leg) in fallback_sources:
                count += 1
                logger.info(
                    "[naked_put] short leg fallback geaccepteerd via %s (parity niet beschikbaar)",
                    _source(leg),
                )
        return True, count, allowed, None

    fallback_count = sum(
        1
        for leg in legs
        if _source(leg) in fallback_sources
    )
    return fallback_count <= allowed, fallback_count, allowed, None


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
        short = [l for l in legs if l.get("position") < 0][0]
        strike = float(short.get("strike"))
        if strategy == "short_put_spread":
            return [strike - credit_ps]
        return [strike + credit_ps]
    if strategy in {"iron_condor", "atm_iron_butterfly"}:
        short_put = [
            l
            for l in legs
            if l.get("position") < 0 and get_leg_right(l) == "put"
        ]
        short_call = [
            l
            for l in legs
            if l.get("position") < 0 and get_leg_right(l) == "call"
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


def validate_leg_metrics(strategy_name: str, legs: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Ensure required leg metrics are present."""
    cfg = cfg_get("STRATEGY_CONFIG") or {}
    strat_cfg = cfg.get("strategies", {}).get(strategy_name, {})
    default_cfg = cfg.get("default", {})
    allow_unpriced_wings = bool(
        strat_cfg.get(
            "allow_unpriced_wings",
            default_cfg.get("allow_unpriced_wings", False),
        )
    )

    missing_fields: set[str] = set()
    for leg in legs:
        missing: List[str] = []
        if leg.get("mid") is None:
            missing.append("mid")
        if leg.get("model") is None:
            missing.append("model")
        if leg.get("delta") is None:
            missing.append("delta")
        leg["missing_metrics"] = missing
        if missing:
            if allow_unpriced_wings and (leg.get("position", 0) > 0):
                leg["metrics_ignored"] = True
                logger.info(
                    f"[leg-missing-allowed] {leg['type']} {leg['strike']} {leg['expiry']}: {', '.join(missing)}"
                )
                continue
            logger.info(
                f"[leg-missing] {leg['type']} {leg['strike']} {leg['expiry']}: {', '.join(missing)}"
            )
            missing_fields.update(missing)
    if missing_fields:
        logger.info(
            f"[❌ voorstel afgewezen] {strategy_name} — reason: ontbrekende metrics (details in debug)"
        )
        missing_str = ", ".join(sorted(missing_fields))
        return False, [f"{missing_str} ontbreken — metrics kunnen niet worden berekend"]
    return True, []


def check_liquidity(
    strategy_name: str, legs: List[Dict[str, Any]], crit: CriteriaConfig
) -> Tuple[bool, List[str]]:
    """Validate option volume and open interest against minimum thresholds."""
    min_vol = float(crit.market_data.min_option_volume)
    min_oi = float(crit.market_data.min_option_open_interest)
    if min_vol <= 0 and min_oi <= 0:
        return True, []

    low_liq: List[str] = []
    for leg in legs:
        vol_raw = leg.get("volume")
        try:
            vol = float(vol_raw) if vol_raw not in (None, "") else None
        except Exception:
            vol = None
        oi_raw = leg.get("open_interest")
        try:
            oi = float(oi_raw) if oi_raw not in (None, "") else None
        except Exception:
            oi = None
        exp = leg.get("expiry") or leg.get("expiration")
        strike = leg.get("strike")
        if isinstance(strike, float) and strike.is_integer():
            strike = int(strike)
        if (
            (min_vol > 0 and vol is not None and vol < min_vol)
            or (min_oi > 0 and oi is not None and oi < min_oi)
        ):
            low_liq.append(f"{strike} [{vol or 0}, {oi or 0}, {exp}]")
    if low_liq:
        logger.info(
            f"[{strategy_name}] Onvoldoende volume/open interest voor strikes {', '.join(low_liq)}"
        )
        return False, ["onvoldoende volume/open interest"]
    return True, []


def compute_proposal_metrics(
    strategy_name: str,
    proposal: "StrategyProposal",
    legs: List[Dict[str, Any]],
    crit: CriteriaConfig,
    spot: float | None = None,
) -> Tuple[Optional[float], List[str]]:
    """Compute proposal metrics and return score with reasons."""
    reasons: List[str] = []
    for leg in legs:
        normalize_leg(leg)

    short_deltas = [
        abs(leg.get("delta", 0))
        for leg in legs
        if leg.get("position", 0) < 0 and leg.get("delta") is not None
    ]
    proposal.pos = calculate_pos(sum(short_deltas) / len(short_deltas)) if short_deltas else None

    short_edges: List[float] = []
    for leg in legs:
        if leg.get("position", 0) < 0:
            try:
                edge_val = float(leg.get("edge"))
            except Exception:
                edge_val = math.nan
            if not math.isnan(edge_val):
                short_edges.append(edge_val)
    proposal.edge = round(sum(short_edges) / len(short_edges), 2) if short_edges else None

    missing_mid: List[str] = []
    credits: List[float] = []
    debits: List[float] = []
    for leg in legs:
        mid = leg.get("mid")
        try:
            mid_val = float(mid) if mid is not None else math.nan
        except Exception:
            mid_val = math.nan
        if math.isnan(mid_val):
            missing_mid.append(str(leg.get("strike")))
            continue
        qty = get_leg_qty(leg)
        pos = float(leg.get("position") or 0)
        if pos < 0:
            credits.append(mid_val * qty)
        elif pos > 0:
            debits.append(mid_val * qty)
    credit_short = sum(credits)
    debit_long = sum(debits)
    if missing_mid:
        logger.info(
            f"[{strategy_name}] Ontbrekende bid/ask-data voor strikes {','.join(missing_mid)}"
        )
        reasons.append("ontbrekende bid/ask-data")
    fallbacks = {
        fb
        for leg in legs
        if (fb := leg.get("mid_fallback")) in {"model", "close"}
    }
    if "close" in fallbacks:
        reasons.append("fallback naar close gebruikt voor midprijs")
    if "model" in fallbacks:
        reasons.append("model-mid gebruikt")
    net_credit = credit_short - debit_long
    if strategy_name in POSITIVE_CREDIT_STRATS and net_credit <= 0:
        reasons.append("negatieve credit")
        return None, reasons

    proposal.credit = net_credit * 100
    cost_basis = -net_credit * 100
    risk = heuristic_risk_metrics(legs, cost_basis)
    proposal.max_profit = risk.get("max_profit")
    proposal.max_loss = risk.get("max_loss")
    proposal.profit_estimated = False
    proposal.scenario_info = None

    margin = None
    try:
        margin = calculate_margin(strategy_name, legs, net_cashflow=net_credit)
    except Exception:
        margin = None
    if margin is None or (isinstance(margin, float) and math.isnan(margin)):
        reasons.append("margin kon niet worden berekend")
        return None, reasons
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

    proposal.rom = calculate_rom(proposal.max_profit, margin) if proposal.max_profit is not None and margin else None
    if proposal.rom is None:
        reasons.append("ROM kon niet worden berekend omdat margin ontbreekt")
    proposal.ev = (
        calculate_ev(proposal.pos or 0.0, proposal.max_profit or 0.0, proposal.max_loss or 0.0)
        if proposal.pos is not None and proposal.max_profit is not None and proposal.max_loss is not None
        else None
    )
    proposal.ev_pct = (proposal.ev / margin) * 100 if proposal.ev is not None and margin else None

    rom_w = float(crit.strategy.score_weight_rom)
    pos_w = float(crit.strategy.score_weight_pos)
    ev_w = float(crit.strategy.score_weight_ev)

    score_val = 0.0
    if proposal.rom is not None:
        score_val += proposal.rom * rom_w
    if proposal.pos is not None:
        score_val += proposal.pos * pos_w
    if proposal.ev_pct is not None:
        score_val += proposal.ev_pct * ev_w

    proposal.breakevens = calculate_breakevens(strategy_name, legs, net_credit * 100)

    if (proposal.ev_pct is not None and proposal.ev_pct <= 0 and not proposal.profit_estimated) or score_val < 0:
        reasons.append("negatieve EV of score")
        logger.info(
            f"[❌ voorstel afgewezen] {strategy_name} — reason: EV/score te laag"
        )
        return None, reasons

    proposal.score = round(score_val, 2)
    if fallbacks:
        proposal.fallback = ",".join(sorted(fallbacks))
    return proposal.score, reasons


def calculate_score(
    strategy: str | Any,
    proposal: "StrategyProposal",
    spot: float | None = None,
    *,
    criteria: CriteriaConfig | None = None,
) -> Tuple[Optional[float], List[str]]:
    """Populate proposal metrics and return the computed score."""

    legs = proposal.legs
    strategy_name = getattr(strategy, "value", strategy)
    _bs_estimate_missing(legs)

    fallback_ok, fallback_count, fallback_allowed, fallback_reason = _fallback_limit_ok(
        strategy_name, legs
    )
    if not fallback_ok:
        if fallback_reason:
            if fallback_allowed:
                reason = f"{fallback_reason} ({fallback_count}/{fallback_allowed} toegestaan)"
            else:
                reason = fallback_reason
        else:
            reason = f"te veel fallback-legs ({fallback_count}/{fallback_allowed} toegestaan)"
        logger.info(f"[{strategy_name}] {reason}")
        return None, [reason]

    valid, reasons = validate_leg_metrics(strategy_name, legs)
    if not valid:
        return None, reasons

    crit = criteria or load_criteria()
    ok, reasons = check_liquidity(strategy_name, legs, crit)
    if not ok:
        return None, reasons

    return compute_proposal_metrics(strategy_name, proposal, legs, crit, spot)


def passes_risk(proposal: "StrategyProposal" | Mapping[str, Any], min_rr: float) -> bool:
    """Return True if proposal satisfies configured risk/reward."""
    if min_rr <= 0:
        return True
    mp = getattr(proposal, "max_profit", None)
    ml = getattr(proposal, "max_loss", None)
    if mp is None or ml is None or not ml:
        return True
    try:
        rr = mp / abs(ml)
    except Exception:
        return True
    return rr >= min_rr


__all__ = ["calculate_score", "calculate_breakevens", "passes_risk"]
