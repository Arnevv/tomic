"""Validation functions for proposal scoring.

This module contains validators for:
- Entry quality (required metrics)
- Exit tradability (contract data and quotes)
- Liquidity (volume and open interest)
- Mid price fallback limits

Extracted from scoring.py to improve code organization.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from ..core import LegView
from ..core.pricing.mid_tags import (
    MID_SOURCE_ORDER,
    PREVIEW_SOURCES,
    normalize_mid_source,
)
from ..metrics import MidPriceResolver, iter_leg_views
from ..helpers.numeric import safe_float
from ..utils import normalize_leg, get_signed_position
from ..logutils import logger
from ..config import get as cfg_get
from ..criteria import CriteriaConfig
from ..strategy.reasons import ReasonCategory, ReasonDetail, make_reason


_VALID_MID_SOURCES = set(MID_SOURCE_ORDER)
_PREVIEW_SOURCES = set(PREVIEW_SOURCES)


def _parse_mid_value(raw_mid: Any) -> tuple[bool, float | None]:
    """Parse and validate a mid value."""
    mid_val = safe_float(raw_mid, accept_nan=False)
    if mid_val is None:
        return False, None
    return True, mid_val


def _resolve_mid_source(leg: Mapping[str, Any]) -> str:
    """Resolve the normalized mid source from leg data."""
    return (
        normalize_mid_source(
            leg.get("mid_source"),
            (leg.get("mid_fallback"),),
        )
        or ""
    )


def validate_entry_quality(
    strategy_name: str, legs: List[Dict[str, Any]]
) -> Tuple[bool, List[ReasonDetail]]:
    """Ensure required leg metrics are present for fresh entries.

    Parameters
    ----------
    strategy_name:
        Name of the strategy being validated
    legs:
        List of leg dictionaries with option data

    Returns
    -------
    tuple
        (is_valid, list of rejection reasons)
    """
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
        leg_type = leg.get("type") or leg.get("right") or leg.get("secType") or "?"
        strike = leg.get("strike")
        strike_suffix = "" if strike in {None, ""} else str(strike)
        mid_display = mid_val if has_mid else leg.get("mid")
        logger.debug(
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
            strike_display = leg.get("strike", "?")
            expiry_display = leg.get("expiry") or leg.get("expiration") or "?"
            if allow_unpriced_wings and (leg.get("position", 0) > 0):
                leg["metrics_ignored"] = True
                logger.info(
                    f"[leg-missing-allowed] {leg_type} {strike_display} {expiry_display}: {', '.join(missing)}"
                )
                continue
            logger.info(
                f"[leg-missing] {leg_type} {strike_display} {expiry_display}: {', '.join(missing)}"
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


def validate_leg_metrics(
    strategy_name: str, legs: List[Dict[str, Any]]
) -> Tuple[bool, List[ReasonDetail]]:
    """Backward compatible wrapper for entry metric validation."""
    return validate_entry_quality(strategy_name, legs)


def validate_exit_tradability(
    strategy_name: str, legs: List[Dict[str, Any]]
) -> Tuple[bool, List[ReasonDetail]]:
    """Check whether ``legs`` contain enough data to close an existing combo.

    Parameters
    ----------
    strategy_name:
        Name of the strategy being validated
    legs:
        List of leg dictionaries with option data

    Returns
    -------
    tuple
        (is_valid, list of rejection reasons)
    """
    missing_contract: list[str] = []
    missing_quotes: list[str] = []
    invalid_quotes: list[str] = []

    for idx, leg in enumerate(legs, start=1):
        normalize_leg(leg)
        con_id = leg.get("conId") or leg.get("con_id")
        if con_id in (None, ""):
            missing_contract.append(f"leg{idx}")

        bid = safe_float(leg.get("bid"))
        ask = safe_float(leg.get("ask"))

        if bid is None or ask is None:
            missing_quotes.append(f"leg{idx}")
            logger.info(
                f"[exit-metrics] {strategy_name} leg{idx} ontbrekende quotes"
            )
            continue

        if bid < 0 or ask < 0 or bid > ask + 1e-9:
            invalid_quotes.append(f"leg{idx}")
            logger.info(
                f"[exit-metrics] {strategy_name} leg{idx} ongeldige quotes bid={bid} ask={ask}"
            )

    if missing_contract:
        message = "contractgegevens ontbreken"
        return False, [
            make_reason(
                ReasonCategory.MISSING_DATA,
                "EXIT_CONTRACT_INCOMPLETE",
                message,
                data={"legs": missing_contract},
            )
        ]

    if missing_quotes:
        message = "niet verhandelbaar (geen quote)"
        return False, [
            make_reason(
                ReasonCategory.MISSING_DATA,
                "EXIT_QUOTES_MISSING",
                message,
                data={"legs": missing_quotes},
            )
        ]

    if invalid_quotes:
        message = "niet verhandelbaar (ongeldige quote)"
        return False, [
            make_reason(
                ReasonCategory.MISSING_DATA,
                "EXIT_QUOTES_INVALID",
                message,
                data={"legs": invalid_quotes},
            )
        ]

    return True, []


def check_liquidity(
    strategy_name: str, legs: List[Dict[str, Any]], crit: CriteriaConfig
) -> Tuple[bool, List[ReasonDetail]]:
    """Validate option volume and open interest against minimum thresholds.

    Parameters
    ----------
    strategy_name:
        Name of the strategy being validated
    legs:
        List of leg dictionaries with option data
    crit:
        Criteria configuration with liquidity thresholds

    Returns
    -------
    tuple
        (is_valid, list of rejection reasons)
    """
    min_vol = float(crit.market_data.min_option_volume)
    min_oi = float(crit.market_data.min_option_open_interest)
    if min_vol <= 0 and min_oi <= 0:
        return True, []

    low_liq: List[dict[str, object]] = []
    for leg in legs:
        vol_raw = leg.get("volume")
        try:
            vol = float(vol_raw) if vol_raw not in (None, "") else None
        except (TypeError, ValueError):
            vol = None
        oi_raw = leg.get("open_interest")
        try:
            oi = float(oi_raw) if oi_raw not in (None, "") else None
        except (TypeError, ValueError):
            oi = None
        exp = leg.get("expiry") or leg.get("expiration")
        strike = leg.get("strike")
        if isinstance(strike, float) and strike.is_integer():
            strike = int(strike)
        if (
            (min_vol > 0 and vol is not None and vol < min_vol)
            or (min_oi > 0 and oi is not None and oi < min_oi)
        ):
            low_liq.append(
                {
                    "strike": strike,
                    "volume": vol if vol is not None else 0,
                    "open_interest": oi if oi is not None else 0,
                    "expiry": exp,
                }
            )
    if low_liq:
        formatted = [
            f"{entry.get('strike')} [{entry.get('volume')}, {entry.get('open_interest')}, {entry.get('expiry')}]"
            for entry in low_liq
        ]
        logger.info(
            f"[{strategy_name}] Onvoldoende volume/open interest voor strikes {', '.join(formatted)}"
        )
        # Vind de laagste waarden
        min_volume = min(entry.get("volume", 0) for entry in low_liq)
        min_oi_val = min(entry.get("open_interest", 0) for entry in low_liq)
        message = f"onvoldoende volume/open interest (min vol: {min_volume}, min OI: {min_oi_val})"
        return False, [
            make_reason(
                ReasonCategory.LOW_LIQUIDITY,
                "LOW_LIQUIDITY_VOLUME",
                message,
                data={"legs": list(low_liq)},
            )
        ]
    return True, []


def fallback_limit_ok(
    strategy_name: str, legs: Sequence[Dict[str, Any] | LegView]
) -> tuple[bool, int, int, str | None]:
    """Check if fallback mid sources are within allowed limits.

    Parameters
    ----------
    strategy_name:
        Name of the strategy being validated
    legs:
        List of leg dictionaries or LegView objects

    Returns
    -------
    tuple
        (is_ok, fallback_count, allowed_count, reason_if_rejected)
    """
    limit_per_four = int(cfg_get("MID_FALLBACK_MAX_PER_4", 2) or 0)
    leg_views = list(iter_leg_views(legs, price_resolver=MidPriceResolver))
    leg_count = len(leg_views)
    if leg_count == 0:
        return True, 0, 0, None
    if limit_per_four <= 0:
        allowed = 0
    else:
        allowed = math.ceil(limit_per_four * leg_count / 4)

    strat_label = getattr(strategy_name, "value", strategy_name)

    def _source(view: LegView) -> str:
        return normalize_mid_source(view.mid_source) or ""

    def _is_long(view: LegView) -> bool:
        return view.signed_position > 0

    fallback_sources = {"model", "close", "parity_close"}
    long_fallbacks = [
        view for view in leg_views if _is_long(view) and _source(view) in fallback_sources
    ]
    short_fallbacks = [
        view for view in leg_views if not _is_long(view) and _source(view) in fallback_sources
    ]
    total_fallbacks = len(long_fallbacks) + len(short_fallbacks)

    def _warn_short_fallbacks() -> None:
        if not short_fallbacks:
            return
        for view in short_fallbacks:
            strike = view.strike
            expiry = view.expiry
            right = (view.right or "?").upper()
            logger.warning(
                f"[{strat_label}] ⚠️ short leg fallback via {_source(view)} — "
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
        long_fallback_legs = [
            view for view in leg_views if _is_long(view) and _source(view) in fallback_sources
        ]
        _warn_short_fallbacks()
        long_count = len(long_fallback_legs)
        if any(_source(view) == "model" for view in long_fallback_legs):
            return False, long_count, allowed, "calendar long leg vereist parity of close"
        if long_count > allowed:
            reason = "te veel fallback-legs op long hedge"
            return False, long_count, allowed, reason
        return long_count <= allowed, long_count, allowed, None

    if strat_label == "naked_put":
        allowed = min(allowed, 1) if allowed else 0
        for view in leg_views:
            if _source(view) in fallback_sources:
                logger.info(
                    "[naked_put] short leg fallback geaccepteerd via %s",
                    _source(view),
                )
        return total_fallbacks <= allowed, total_fallbacks, allowed, None

    return total_fallbacks <= allowed, total_fallbacks, allowed, None


def preview_penalty(
    strategy_name: str,
    fallback_summary: Mapping[str, int],
    *,
    preview_sources: Iterable[str],
    short_preview_legs: int,
    long_preview_legs: int,
    total_legs: int,
    fallback_count: int,
    fallback_allowed: int,
    fallback_reason: str | None,
    fallback_warning: str | None,
) -> tuple[float, ReasonDetail | None, bool]:
    """Calculate score penalty for preview/fallback mid sources.

    Parameters
    ----------
    strategy_name:
        Name of the strategy being scored
    fallback_summary:
        Dict mapping fallback source names to counts
    preview_sources:
        Iterable of preview source names used
    short_preview_legs:
        Number of short legs using preview sources
    long_preview_legs:
        Number of long legs using preview sources
    total_legs:
        Total number of legs in the strategy
    fallback_count:
        Actual number of fallback legs
    fallback_allowed:
        Maximum allowed fallback legs
    fallback_reason:
        Rejection reason if fallback limit exceeded
    fallback_warning:
        Warning message for fallback usage

    Returns
    -------
    tuple
        (penalty_amount, reason_detail or None, needs_refresh flag)
    """
    preview_leg_count = sum(fallback_summary.get(src, 0) for src in _PREVIEW_SOURCES)
    if preview_leg_count <= 0 or total_legs <= 0:
        return 0.0, None, False

    scoring_cfg = cfg_get("SCORING", {}) or {}
    preview_cfg = scoring_cfg.get("mid_preview") or {}
    per_leg = float(preview_cfg.get("penalty_per_leg", 1.5))
    max_ratio = float(preview_cfg.get("max_preview_ratio", 0.5) or 0.0)
    max_penalty = float(preview_cfg.get("penalty_cap", per_leg * total_legs))
    short_multiplier = float(preview_cfg.get("short_leg_multiplier", 1.0))
    min_penalty = float(preview_cfg.get("min_penalty", 0.0))

    ratio = preview_leg_count / total_legs if total_legs else 0.0
    severity = 1.0
    if max_ratio > 0:
        severity = min(max(ratio / max_ratio, 0.0), 1.0)

    penalty = per_leg * preview_leg_count * severity
    if short_preview_legs > 0 and short_multiplier > 0:
        penalty *= max(short_multiplier, 0.0)
    if max_penalty > 0:
        penalty = min(penalty, max_penalty)
    if min_penalty > 0:
        penalty = max(penalty, min_penalty)

    penalty = round(penalty, 2)
    data: dict[str, Any] = {
        "strategy": strategy_name,
        "preview_sources": sorted(set(preview_sources)),
        "preview_leg_count": preview_leg_count,
        "total_leg_count": total_legs,
        "preview_ratio": round(ratio, 4),
        "max_preview_ratio": max_ratio if max_ratio > 0 else None,
        "short_preview_legs": short_preview_legs or None,
        "long_preview_legs": long_preview_legs or None,
        "penalty_per_leg": per_leg,
        "penalty_severity": round(severity, 4),
        "penalty_cap": max_penalty if max_penalty > 0 else None,
        "estimated_penalty": penalty,
        "score_impact": 0.0,
        "fallback_limit_count": fallback_count,
        "fallback_limit_allowed": fallback_allowed,
        "fallback_limit_reason": fallback_reason,
    }
    data = {key: value for key, value in data.items() if value not in (None, [])}

    message = (
        f"preview mids gebruikt voor {preview_leg_count}/{total_legs} legs"
        if total_legs
        else "preview mids gebruikt"
    )
    limit_message = fallback_warning or fallback_reason
    if limit_message:
        data["fallback_limit_message"] = limit_message
        message = f"{message} — {limit_message}"
    detail = make_reason(
        ReasonCategory.PREVIEW_QUALITY,
        "MID_PREVIEW_PENALTY",
        message,
        data=data,
    )
    return penalty, detail, True


__all__ = [
    "validate_entry_quality",
    "validate_leg_metrics",
    "validate_exit_tradability",
    "check_liquidity",
    "fallback_limit_ok",
    "preview_penalty",
]
