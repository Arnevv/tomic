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
from ..helpers.dateutils import parse_date
from ..utils import normalize_leg, get_leg_qty, get_leg_right, today
from ..logutils import logger
from ..config import get as cfg_get
from ..strategy.reasons import (
    ReasonCategory,
    ReasonDetail,
    make_reason,
    reason_from_mid_source,
)

if TYPE_CHECKING:
    from tomic.strategy_candidates import StrategyProposal

POSITIVE_CREDIT_STRATS = set(RULES.strategy.acceptance.require_positive_credit_for)


_VALID_MID_SOURCES = {"true", "parity_true", "parity_close", "model", "close"}


def _safe_float(value: Any) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(val):
        return None
    return val


def _max_credit_for_strategy(strategy: str, legs: List[Dict[str, Any]]) -> float | None:
    strat = strategy.lower()
    if strat == "short_put_spread":
        return _vertical_width(legs, "put")
    if strat == "short_call_spread":
        return _vertical_width(legs, "call")
    if strat in {"iron_condor", "atm_iron_butterfly"}:
        put_cap = _vertical_width(legs, "put")
        call_cap = _vertical_width(legs, "call")
        if put_cap is None and call_cap is None:
            return None
        values = [val for val in (put_cap, call_cap) if val is not None]
        return max(values) if values else None
    return None


def _find_leg(
    legs: List[Dict[str, Any]], right: str, *, short: bool
) -> Dict[str, Any] | None:
    for leg in legs:
        if get_leg_right(leg) != right:
            continue
        position = float(leg.get("position") or leg.get("qty") or 0)
        if short and position < 0:
            return leg
        if not short and position > 0:
            return leg
    return None


def _vertical_width(legs: List[Dict[str, Any]], right: str) -> float | None:
    short_leg = _find_leg(legs, right, short=True)
    long_leg = _find_leg(legs, right, short=False)
    if not short_leg or not long_leg:
        return None
    short_strike = _safe_float(short_leg.get("strike"))
    long_strike = _safe_float(long_leg.get("strike"))
    if short_strike is None or long_strike is None:
        return None
    if right == "put":
        width = short_strike - long_strike
    else:
        width = long_strike - short_strike
    if width <= 0:
        return None
    try:
        qty = get_leg_qty(short_leg)
    except Exception:
        qty = 1
    return width * max(qty, 1)


def _collect_leg_values(legs: List[Dict[str, Any]], keys: Tuple[str, ...]) -> List[float]:
    values: List[float] = []
    targets = {key.lower().replace("_", "") for key in keys}
    for leg in legs:
        for raw_key, raw_value in leg.items():
            canonical = str(raw_key).lower().replace("_", "")
            if canonical not in targets:
                continue
            val = _safe_float(raw_value)
            if val is None:
                continue
            values.append(val)
            break
    return values


def _infer_leg_dte(leg: Mapping[str, Any]) -> Optional[int]:
    for key in ("dte", "days_to_expiry", "DTE"):
        raw = leg.get(key)
        if raw in (None, ""):
            continue
        val = _safe_float(raw)
        if val is None:
            continue
        return int(round(val))
    expiry = leg.get("expiry") or leg.get("expiration")
    if not expiry:
        return None
    exp_date = parse_date(str(expiry))
    if exp_date is None:
        return None
    return (exp_date - today()).days


def _compute_wing_metrics(legs: List[Dict[str, Any]]) -> tuple[Dict[str, float] | None, bool | None]:
    widths: Dict[str, float] = {}
    for right in ("call", "put"):
        short_legs: List[Dict[str, Any]] = []
        long_legs: List[Dict[str, Any]] = []
        for leg in legs:
            if get_leg_right(leg) != right:
                continue
            pos_val = _safe_float(leg.get("position"))
            if pos_val is None or _safe_float(leg.get("strike")) is None:
                continue
            if pos_val < 0:
                short_legs.append(leg)
            elif pos_val > 0:
                long_legs.append(leg)
        if not short_legs or not long_legs:
            continue
        distances: List[float] = []
        long_strikes = [
            _safe_float(l.get("strike"))
            for l in long_legs
            if _safe_float(l.get("strike")) is not None
        ]
        long_strikes = [v for v in long_strikes if v is not None]
        for short in short_legs:
            short_strike = _safe_float(short.get("strike"))
            if short_strike is None:
                continue
            candidates: List[float] = []
            for long in long_strikes:
                if long is None:
                    continue
                if right == "call" and long <= short_strike:
                    continue
                if right == "put" and long >= short_strike:
                    continue
                candidates.append(abs(long - short_strike))
            if not candidates:
                candidates = [
                    abs(long - short_strike) for long in long_strikes if long is not None
                ]
            if candidates:
                distances.append(min(candidates))
        if distances:
            widths[right] = sum(distances) / len(distances)
    if not widths:
        return None, None
    symmetry: bool | None = None
    if "call" in widths and "put" in widths:
        call_width = abs(widths["call"])
        put_width = abs(widths["put"])
        max_width = max(call_width, put_width, 1e-6)
        symmetry = abs(call_width - put_width) <= max_width * 0.05
    return widths, symmetry


def _populate_additional_metrics(
    proposal: "StrategyProposal", legs: List[Dict[str, Any]], spot: float | None
) -> None:
    atr_values = _collect_leg_values(legs, ("ATR14", "atr14", "atr"))
    if getattr(proposal, "atr", None) is None and atr_values:
        proposal.atr = atr_values[0]

    iv_rank_vals = _collect_leg_values(legs, ("IV_Rank", "iv_rank"))
    if iv_rank_vals:
        proposal.iv_rank = sum(iv_rank_vals) / len(iv_rank_vals)

    iv_percentile_vals = _collect_leg_values(legs, ("IV_Percentile", "iv_percentile"))
    if iv_percentile_vals:
        proposal.iv_percentile = sum(iv_percentile_vals) / len(iv_percentile_vals)

    hv20_vals = _collect_leg_values(legs, ("HV20", "hv20"))
    if hv20_vals:
        proposal.hv20 = sum(hv20_vals) / len(hv20_vals)

    hv30_vals = _collect_leg_values(legs, ("HV30", "hv30"))
    if hv30_vals:
        proposal.hv30 = sum(hv30_vals) / len(hv30_vals)

    hv90_vals = _collect_leg_values(legs, ("HV90", "hv90"))
    if hv90_vals:
        proposal.hv90 = sum(hv90_vals) / len(hv90_vals)

    dte_by_expiry: Dict[str, int] = {}
    for leg in legs:
        expiry = leg.get("expiry") or leg.get("expiration")
        if not expiry:
            continue
        dte_val = _infer_leg_dte(leg)
        if dte_val is None:
            continue
        dte_by_expiry[str(expiry)] = dte_val
    if dte_by_expiry:
        unique_values = sorted(set(dte_by_expiry.values()))
        proposal.dte = {
            "min": min(unique_values),
            "max": max(unique_values),
            "values": unique_values,
            "by_expiry": dte_by_expiry,
        }
    else:
        proposal.dte = None

    widths, symmetry = _compute_wing_metrics(legs)
    proposal.wing_width = widths
    proposal.wing_symmetry = symmetry

    distances: List[float] = []
    percents: List[float] = []
    spot_val = _safe_float(spot)
    if spot_val not in (None, 0):
        for be in getattr(proposal, "breakevens", []) or []:
            be_val = _safe_float(be)
            if be_val is None:
                continue
            diff = abs(be_val - spot_val)
            distances.append(diff)
            percents.append((diff / spot_val) * 100)
    proposal.breakeven_distances = {
        "dollar": distances,
        "percent": percents,
    }


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
        source = str(leg.get("mid_source") or leg.get("mid_fallback") or "")
        if source == "parity":
            return "parity_true"
        return source

    def _is_long(leg: Mapping[str, Any]) -> bool:
        try:
            return float(leg.get("position") or 0) > 0
        except Exception:
            return False

    fallback_sources = {"model", "close", "parity_close"}
    long_fallbacks = [
        leg for leg in legs if _is_long(leg) and _source(leg) in fallback_sources
    ]
    short_fallbacks = [
        leg for leg in legs if not _is_long(leg) and _source(leg) in fallback_sources
    ]
    total_fallbacks = len(long_fallbacks) + len(short_fallbacks)

    def _warn_short_fallbacks() -> None:
        if not short_fallbacks:
            return
        for leg in short_fallbacks:
            try:
                strike = leg.get("strike")
                expiry = leg.get("expiry")
                right = get_leg_right(leg).upper()
            except Exception:  # pragma: no cover - defensive logging
                strike = leg.get("strike")
                expiry = leg.get("expiry")
                right = str(leg.get("type") or "?").upper()
            logger.warning(
                f"[{strat_label}] ⚠️ short leg fallback via {_source(leg)} — "
                f"{right} {strike} {expiry}"
            )

    if strat_label in {
        "iron_condor",
        "atm_iron_butterfly",
        "ratio_spread",
        "backspread_put",
    }:
        allowed = min(allowed, 2) if allowed else 0
        _warn_short_fallbacks()
        long_count = len(long_fallbacks)
        if long_count > allowed:
            reason = "te veel fallback-legs op long wings"
            return False, long_count, allowed, reason
        return long_count <= allowed, long_count, allowed, None

    if strat_label in {"short_call_spread", "short_put_spread"}:
        allowed = min(allowed, 1) if allowed else 0
        _warn_short_fallbacks()
        long_count = len(long_fallbacks)
        if long_count > allowed:
            reason = "te veel fallback-legs op long hedge"
            return False, long_count, allowed, reason
        return long_count <= allowed, long_count, allowed, None

    if strat_label == "calendar":
        allowed = min(allowed, 1) if allowed else 0
        long_fallback_legs = [leg for leg in legs if _is_long(leg) and _source(leg) in fallback_sources]
        _warn_short_fallbacks()
        long_count = len(long_fallback_legs)
        if any(_source(leg) == "model" for leg in long_fallback_legs):
            return False, long_count, allowed, "calendar long leg vereist parity of close"
        if long_count > allowed:
            reason = "te veel fallback-legs op long hedge"
            return False, long_count, allowed, reason
        return long_count <= allowed, long_count, allowed, None

    if strat_label == "naked_put":
        allowed = min(allowed, 1) if allowed else 0
        for leg in legs:
            if _source(leg) in fallback_sources:
                logger.info(
                    "[naked_put] short leg fallback geaccepteerd via %s",
                    _source(leg),
                )
        return total_fallbacks <= allowed, total_fallbacks, allowed, None

    return total_fallbacks <= allowed, total_fallbacks, allowed, None


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


def _parse_mid_value(raw_mid: Any) -> tuple[bool, float | None]:
    try:
        mid_val = float(raw_mid)
    except (TypeError, ValueError):
        return False, None
    if math.isnan(mid_val):
        return False, None
    return True, mid_val


def _resolve_mid_source(leg: Mapping[str, Any]) -> str:
    source = str(leg.get("mid_fallback") or leg.get("mid_source") or "").strip().lower()
    if source == "parity":
        source = "parity_true"
    return source


def validate_leg_metrics(
    strategy_name: str, legs: List[Dict[str, Any]]
) -> Tuple[bool, List[ReasonDetail]]:
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
        has_mid, mid_val = _parse_mid_value(leg.get("mid"))
        if has_mid and mid_val is not None:
            leg["mid"] = mid_val
        source = _resolve_mid_source(leg)
        source_ok = (not source) or (source in _VALID_MID_SOURCES)
        has_price = has_mid and source_ok
        leg_type = leg.get("type") or "?"
        strike = leg.get("strike")
        strike_suffix = "" if strike in {None, ""} else str(strike)
        mid_display = mid_val if has_mid else leg.get("mid")
        logger.info(
            f"[mid-check] {strategy_name} leg {leg_type}{strike_suffix} -> has_mid={has_price} "
            f"(value={mid_display}, source={source or '—'}, bid={leg.get('bid')}, "
            f"ask={leg.get('ask')}, close={leg.get('close')}, source_ok={source_ok})"
        )
        if not has_price:
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
        message = f"{missing_str} ontbreken — metrics kunnen niet worden berekend"
        return False, [make_reason(ReasonCategory.MISSING_DATA, "METRICS_MISSING", message)]
    return True, []


def check_liquidity(
    strategy_name: str, legs: List[Dict[str, Any]], crit: CriteriaConfig
) -> Tuple[bool, List[ReasonDetail]]:
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
        return False, [
            make_reason(
                ReasonCategory.LOW_LIQUIDITY,
                "LOW_LIQUIDITY_VOLUME",
                "onvoldoende volume/open interest",
                data={"legs": list(low_liq)},
            )
        ]
    return True, []


def compute_proposal_metrics(
    strategy_name: str,
    proposal: "StrategyProposal",
    legs: List[Dict[str, Any]],
    crit: CriteriaConfig,
    spot: float | None = None,
) -> Tuple[Optional[float], List[ReasonDetail]]:
    """Compute proposal metrics and return score with structured reasons."""

    reasons: List[ReasonDetail] = []
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
    raw_fallback_sources: set[str] = set()

    for leg in legs:
        mid = leg.get("mid")
        try:
            mid_val = float(mid) if mid is not None else math.nan
        except Exception:
            mid_val = math.nan
        if math.isnan(mid_val):
            missing_mid.append(str(leg.get("strike")))
        else:
            qty = get_leg_qty(leg)
            pos = float(leg.get("position") or 0)
            if pos < 0:
                credits.append(mid_val * qty)
            elif pos > 0:
                debits.append(mid_val * qty)
        fallback = str(leg.get("mid_fallback") or "").strip().lower()
        if fallback:
            raw_fallback_sources.add(fallback)

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

    preview_sources: set[str] = set()
    for source in sorted(raw_fallback_sources):
        detail = reason_from_mid_source(source)
        if detail is not None:
            preview_sources.add(source)
        _add_reason(detail)

    credit_short = sum(credits)
    debit_long = sum(debits)
    net_credit = credit_short - debit_long

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
        return None, reasons

    proposal.credit = net_credit * 100
    proposal.credit_capped = credit_capped
    cost_basis = -net_credit * 100
    risk = heuristic_risk_metrics(legs, cost_basis)
    proposal.max_profit = risk.get("max_profit")
    proposal.max_loss = risk.get("max_loss")
    proposal.profit_estimated = False
    proposal.scenario_info = None

    try:
        margin = calculate_margin(strategy_name, legs, net_cashflow=net_credit)
    except Exception:
        margin = None

    if margin is None or (isinstance(margin, float) and math.isnan(margin)):
        _add_reason(
            make_reason(
                ReasonCategory.MISSING_DATA,
                "MARGIN_MISSING",
                "margin kon niet worden berekend",
            )
        )
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
        _add_reason(
            make_reason(
                ReasonCategory.EV_BELOW_MIN,
                "EV_TOO_LOW",
                "negatieve EV of score",
            )
        )
        logger.info(
            f"[❌ voorstel afgewezen] {strategy_name} — reason: EV/score te laag"
        )
        return None, reasons

    proposal.score = round(score_val, 2)
    if preview_sources:
        proposal.fallback = ",".join(sorted(preview_sources))
    else:
        proposal.fallback = None
    return proposal.score, reasons


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
    if not fallback_ok:
        if fallback_reason:
            if fallback_allowed:
                message = f"{fallback_reason} ({fallback_count}/{fallback_allowed} toegestaan)"
            else:
                message = fallback_reason
        else:
            message = f"te veel fallback-legs ({fallback_count}/{fallback_allowed} toegestaan)"
        logger.info(f"[{strategy_name}] {message}")
        return None, [
            make_reason(
                ReasonCategory.POLICY_VIOLATION,
                "FALLBACK_LIMIT", message,
                data={"fallback_count": fallback_count, "allowed": fallback_allowed},
            )
        ]

    valid, reasons = validate_leg_metrics(strategy_name, legs)
    if not valid:
        return None, reasons

    crit = criteria or load_criteria()
    ok, reasons = check_liquidity(strategy_name, legs, crit)
    if not ok:
        return None, reasons

    score, reasons = compute_proposal_metrics(strategy_name, proposal, legs, crit, spot)
    _populate_additional_metrics(proposal, legs, spot)
    return score, reasons


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
