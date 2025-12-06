"""Helper functions for proposal scoring.

This module contains utility functions for:
- Configuration resolution
- Value normalization
- Credit and leg calculations
- Metric population

Extracted from scoring.py to improve code organization.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, TYPE_CHECKING

from ..helpers.dateutils import parse_date
from ..helpers.numeric import safe_float
from ..utils import get_leg_qty, get_leg_right, get_signed_position, today
from ..config import get as cfg_get
from ..criteria import CriteriaConfig, RULES
from ..metrics import aggregate_greeks, PROPOSAL_GREEK_SCHEMA

if TYPE_CHECKING:
    from tomic.strategy_candidates import StrategyProposal


# Sanity check thresholds for suspicious metrics
CREDIT_TO_WIDTH_WARN_RATIO = 0.80  # Warn if credit > 80% of wing width
ROM_WARN_THRESHOLD = 500.0  # Warn if ROM > 500%
MARGIN_MIN_THRESHOLD = 50.0  # Warn if margin < $50 per contract


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Clamp a value between minimum and maximum bounds."""
    return max(minimum, min(maximum, value))


def normalize_ratio(value: float | None, cap: float) -> float | None:
    """Normalize a value as ratio of a cap, clamped to [0, 1]."""
    if value is None or cap <= 0:
        return None
    return clamp(value / cap)


def normalize_pos(value: float | None, floor: float, span: float) -> float | None:
    """Normalize a position value relative to floor and span."""
    if value is None or span <= 0:
        return None
    return clamp((value - floor) / span)


def normalize_risk_reward(value: float | None, criteria_cfg: CriteriaConfig) -> float | None:
    """Normalize risk/reward using configurable linear + logarithmic scaling.

    The normalization uses:
    1. Linear scaling from floor to linear_cap
    2. Logarithmic scaling from linear_cap to log_cap

    Parameters
    ----------
    value:
        Raw risk/reward value
    criteria_cfg:
        Configuration with normalization parameters
    """
    if value is None:
        return None
    rr_floor = float(criteria_cfg.strategy.rr_floor)
    if value <= rr_floor:
        return 0.0

    linear_cap = max(float(criteria_cfg.strategy.rr_linear_cap), rr_floor)
    linear_ceiling = clamp(float(criteria_cfg.strategy.rr_linear_ceiling), 0.0, 1.0)
    exponent = float(criteria_cfg.strategy.rr_exponent)
    rr_log_cap = max(float(criteria_cfg.strategy.rr_log_cap), linear_cap)
    log_base = max(float(criteria_cfg.strategy.rr_log_base), 0.0)

    if linear_cap <= rr_floor:
        linear_component = 0.0
    else:
        ratio = (min(value, linear_cap) - rr_floor) / (linear_cap - rr_floor)
        ratio = max(0.0, ratio)
        try:
            linear_component = ratio**exponent
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            linear_component = ratio
        linear_component = clamp(linear_component) * linear_ceiling

    if value <= linear_cap or rr_log_cap <= linear_cap:
        return linear_component

    excess = min(value, rr_log_cap) - linear_cap
    log_range = rr_log_cap - linear_cap
    if log_range <= 0:
        return linear_component

    if log_base > 0:
        numerator = math.log1p(excess * log_base)
        denominator = math.log1p(log_range * log_base)
    else:
        numerator = math.log1p(excess)
        denominator = math.log1p(log_range)

    if denominator <= 0:
        log_component = 1.0
    else:
        log_component = clamp(numerator / denominator)

    return clamp(linear_ceiling + (1.0 - linear_ceiling) * log_component)


def resolve_strategy_config(strategy_name: str) -> Mapping[str, Any]:
    """Resolve merged strategy configuration from defaults and strategy-specific settings."""
    cfg = cfg_get("STRATEGY_CONFIG") or {}
    default_cfg = cfg.get("default", {}) if isinstance(cfg, Mapping) else {}
    strat_cfg = cfg.get("strategies", {}).get(strategy_name, {}) if isinstance(cfg, Mapping) else {}
    merged: dict[str, Any] = {}
    if isinstance(default_cfg, Mapping):
        merged.update(default_cfg)
    if isinstance(strat_cfg, Mapping):
        merged.update(strat_cfg)
    return merged


def resolve_min_risk_reward(
    strategy_cfg: Mapping[str, Any], criteria: CriteriaConfig | None
) -> float:
    """Determine the effective minimum risk/reward threshold.

    Priority order (highest to lowest):
    1. Strategy-specific setting from strategies.yaml
    2. Default from strategies.yaml
    3. Fallback from criteria.yaml
    """
    # Try strategy config first (includes strategy-specific and default from strategies.yaml)
    min_rr = safe_float(strategy_cfg.get("min_risk_reward"))

    # Use criteria.yaml as fallback only if strategy config has no value
    if min_rr is None and criteria is not None:
        try:
            min_rr = safe_float(criteria.strategy.acceptance.min_risk_reward)
        except AttributeError:  # pragma: no cover - defensive
            min_rr = None

    # Final fallback to RULES
    if min_rr is None:
        fallback = safe_float(getattr(RULES.strategy.acceptance, "min_risk_reward", None))
        min_rr = fallback if fallback is not None else 0.0

    return max(0.0, float(min_rr))


def max_credit_for_strategy(strategy: str, legs: List[Dict[str, Any]]) -> float | None:
    """Return the theoretical maximum credit for a spread strategy."""
    strat = strategy.lower()
    if strat == "short_put_spread":
        return vertical_width(legs, "put")
    if strat == "short_call_spread":
        return vertical_width(legs, "call")
    if strat in {"iron_condor", "atm_iron_butterfly"}:
        put_cap = vertical_width(legs, "put")
        call_cap = vertical_width(legs, "call")
        if put_cap is None and call_cap is None:
            return None
        values = [val for val in (put_cap, call_cap) if val is not None]
        return max(values) if values else None
    return None


def find_leg(
    legs: List[Dict[str, Any]], right: str, *, short: bool
) -> Dict[str, Any] | None:
    """Find a leg matching the given right and position direction."""
    for leg in legs:
        if get_leg_right(leg) != right:
            continue
        position = get_signed_position(leg)
        if short and position < 0:
            return leg
        if not short and position > 0:
            return leg
    return None


def vertical_width(legs: List[Dict[str, Any]], right: str) -> float | None:
    """Calculate the width of a vertical spread for the given right (put/call)."""
    short_leg = find_leg(legs, right, short=True)
    long_leg = find_leg(legs, right, short=False)
    if not short_leg or not long_leg:
        return None
    short_strike = safe_float(short_leg.get("strike"))
    long_strike = safe_float(long_leg.get("strike"))
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
    except (TypeError, ValueError, KeyError):
        qty = 1
    return width * max(qty, 1)


def collect_leg_values(legs: List[Dict[str, Any]], keys: Tuple[str, ...]) -> List[float]:
    """Collect numeric values from legs for the specified keys."""
    values: List[float] = []
    targets = {key.lower().replace("_", "") for key in keys}
    for leg in legs:
        for raw_key, raw_value in leg.items():
            canonical = str(raw_key).lower().replace("_", "")
            if canonical not in targets:
                continue
            val = safe_float(raw_value)
            if val is None:
                continue
            values.append(val)
            break
    return values


def infer_leg_dte(leg: Mapping[str, Any]) -> Optional[int]:
    """Infer days-to-expiry from leg data."""
    for key in ("dte", "days_to_expiry", "DTE"):
        raw = leg.get(key)
        if raw in (None, ""):
            continue
        val = safe_float(raw)
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


def compute_wing_metrics(legs: List[Dict[str, Any]]) -> tuple[Dict[str, float] | None, bool | None]:
    """Compute wing width metrics for multi-leg strategies.

    Returns
    -------
    tuple
        (wing_widths dict, symmetry boolean or None)
    """
    widths: Dict[str, float] = {}
    for right in ("call", "put"):
        short_legs: List[Dict[str, Any]] = []
        long_legs: List[Dict[str, Any]] = []
        for leg in legs:
            if get_leg_right(leg) != right:
                continue
            pos_val = get_signed_position(leg)
            if pos_val == 0 or safe_float(leg.get("strike")) is None:
                continue
            if pos_val < 0:
                short_legs.append(leg)
            elif pos_val > 0:
                long_legs.append(leg)
        if not short_legs or not long_legs:
            continue
        distances: List[float] = []
        long_strikes = [
            safe_float(l.get("strike"))
            for l in long_legs
            if safe_float(l.get("strike")) is not None
        ]
        long_strikes = [v for v in long_strikes if v is not None]
        for short in short_legs:
            short_strike = safe_float(short.get("strike"))
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


def populate_additional_metrics(
    proposal: "StrategyProposal", legs: List[Dict[str, Any]], spot: float | None
) -> None:
    """Populate additional metrics on proposal from leg data."""
    greek_totals = aggregate_greeks(legs, schema=PROPOSAL_GREEK_SCHEMA)
    proposal.greeks = dict(greek_totals)
    proposal.greeks_sum = {key.capitalize(): value for key, value in greek_totals.items()}

    atr_values = collect_leg_values(legs, ("ATR14", "atr14", "atr"))
    if getattr(proposal, "atr", None) is None and atr_values:
        proposal.atr = atr_values[0]

    iv_rank_vals = collect_leg_values(legs, ("IV_Rank", "iv_rank"))
    if iv_rank_vals:
        proposal.iv_rank = sum(iv_rank_vals) / len(iv_rank_vals)

    iv_percentile_vals = collect_leg_values(legs, ("IV_Percentile", "iv_percentile"))
    if iv_percentile_vals:
        proposal.iv_percentile = sum(iv_percentile_vals) / len(iv_percentile_vals)

    hv20_vals = collect_leg_values(legs, ("HV20", "hv20"))
    if hv20_vals:
        proposal.hv20 = sum(hv20_vals) / len(hv20_vals)

    hv30_vals = collect_leg_values(legs, ("HV30", "hv30"))
    if hv30_vals:
        proposal.hv30 = sum(hv30_vals) / len(hv30_vals)

    hv90_vals = collect_leg_values(legs, ("HV90", "hv90"))
    if hv90_vals:
        proposal.hv90 = sum(hv90_vals) / len(hv90_vals)

    dte_by_expiry: Dict[str, int] = {}
    for leg in legs:
        expiry = leg.get("expiry") or leg.get("expiration")
        if not expiry:
            continue
        dte_val = infer_leg_dte(leg)
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

    widths, symmetry = compute_wing_metrics(legs)
    proposal.wing_width = widths
    proposal.wing_symmetry = symmetry

    distances: List[float] = []
    percents: List[float] = []
    spot_val = safe_float(spot)
    if spot_val not in (None, 0):
        for be in getattr(proposal, "breakevens", []) or []:
            be_val = safe_float(be)
            if be_val is None:
                continue
            diff = abs(be_val - spot_val)
            distances.append(diff)
            percents.append((diff / spot_val) * 100)
    proposal.breakeven_distances = {
        "dollar": distances,
        "percent": percents,
    }


def bs_estimate_missing(legs: List[Dict[str, Any]]) -> None:
    """Fill missing model price and delta using Black-Scholes."""
    from ..helpers.bs_utils import populate_model_delta

    for leg in legs:
        populate_model_delta(leg)


__all__ = [
    # Constants
    "CREDIT_TO_WIDTH_WARN_RATIO",
    "ROM_WARN_THRESHOLD",
    "MARGIN_MIN_THRESHOLD",
    # Normalization
    "clamp",
    "normalize_ratio",
    "normalize_pos",
    "normalize_risk_reward",
    # Config
    "resolve_strategy_config",
    "resolve_min_risk_reward",
    # Leg calculations
    "max_credit_for_strategy",
    "find_leg",
    "vertical_width",
    "collect_leg_values",
    "infer_leg_dte",
    "compute_wing_metrics",
    # Metrics
    "populate_additional_metrics",
    "bs_estimate_missing",
]
