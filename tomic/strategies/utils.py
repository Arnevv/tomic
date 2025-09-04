"""Utility helpers for strategy modules."""

from __future__ import annotations

import math
from typing import Sequence, Any, Dict, List, Mapping

import pandas as pd
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from tomic.helpers.dateutils import dte_between_dates

from ..utils import normalize_right, get_leg_right, today
from ..logutils import logger
from ..strike_selector import _dte


MAX_PROPOSALS = 5


def reached_limit(proposals: Sequence[Any]) -> bool:
    """Return True if the proposal count reached :data:`MAX_PROPOSALS`."""
    return len(proposals) >= MAX_PROPOSALS


def validate_width_list(widths: Sequence[Any] | Mapping[str, Any] | float | int | None, key: str) -> Sequence[Any]:
    """Return ``widths`` if valid or raise ``ValueError``.

    Parameters
    ----------
    widths:
        The sequence of width values retrieved from configuration.
    key:
        The configuration key the widths originate from. Used for a clear
        error message when validation fails.

    Raises
    ------
    ValueError
        If ``widths`` is ``None`` or empty.
    """

    if widths is None:
        msg = f"'{key}' ontbreekt of is leeg in configuratie"
        logger.error(msg)
        raise ValueError(msg)

    if isinstance(widths, (int, float)) or isinstance(widths, Mapping):
        widths = [widths]

    try:
        seq = list(widths)
    except TypeError:
        msg = f"'{key}' heeft een ongeldig type"
        logger.error(msg)
        raise ValueError(msg)

    if not seq:
        msg = f"'{key}' ontbreekt of is leeg in configuratie"
        logger.error(msg)
        raise ValueError(msg)

    allowed = {"points", "sigma", "delta"}
    for w in seq:
        if isinstance(w, Mapping):
            if not any(k in w for k in allowed):
                msg = f"'{key}' bevat onbekende width specificatie"
                logger.error(msg)
                raise ValueError(msg)

    return seq


def compute_dynamic_width(
    short_opt: Dict[str, Any],
    *,
    spot: float | None = None,
    sigma_multiple: float | None = None,
    target_delta: float | None = None,
    atr_multiple: float | None = None,
    atr: float | None = None,
    use_atr: bool = False,
    option_chain: List[Dict[str, Any]] | None = None,
    expiry: str | None = None,
    option_type: str | None = None,
) -> float | None:
    """Return a dynamic width for the long leg.

    Parameters
    ----------
    short_opt:
        The selected short option used as reference.
    spot:
        Current underlying price. Required for ``sigma_multiple`` scaling.
    sigma_multiple:
        Multiplier applied to one-sigma move. When provided the width is
        calculated as ``spot * sigma_multiple * iv * sqrt(dte/365)`` where
        ``iv`` and ``dte`` are retrieved from ``short_opt``.
    target_delta:
        If provided the width is the distance between ``short_opt`` and the
        option in ``option_chain`` whose delta is closest to ``target_delta``.
    atr_multiple:
        When ``target_delta`` is not supplied, width can be derived from an ATR
        multiple. ``atr`` must also be provided.
    atr:
        Average True Range of the underlying. Used with ``atr_multiple`` when
        ``use_atr`` is True.
    use_atr:
        Flag indicating whether distances are expressed in ATR or absolute
        points.
    option_chain, expiry, option_type:
        Required when ``target_delta`` is used. These parameters scope the
        search for the long option.

    Returns
    -------
    float | None
        Calculated width in strike points or ``None`` when insufficient data is
        available.
    """

    if sigma_multiple is not None and spot is not None:
        try:
            iv = float(short_opt.get("iv"))
            exp = str(short_opt.get("expiry"))
            dte = dte_between_dates(today(), exp)
            return spot * sigma_multiple * iv * math.sqrt(max(dte, 0) / 365)
        except Exception:
            return None

    if target_delta is not None and option_chain and expiry and option_type:
        opt_type = normalize_right(option_type)
        candidates = [
            o
            for o in option_chain
            if str(o.get("expiry")) == expiry
            and get_leg_right(o) == opt_type
            and o.get("delta") is not None
        ]
        if not candidates:
            return None
        try:
            long_opt = min(candidates, key=lambda o: abs(float(o["delta"]) - target_delta))
            return abs(float(short_opt.get("strike")) - float(long_opt.get("strike")))
        except Exception:
            return None

    if atr_multiple is not None and atr is not None:
        try:
            width = atr_multiple * (atr if use_atr else 1.0)
            return abs(width)
        except Exception:
            return None

    return None


def prepare_option_chain(option_chain: List[Dict[str, Any]], spot: float) -> List[Dict[str, Any]]:
    """Return ``option_chain`` as list of dicts with parity-filled mids."""

    if hasattr(pd, "DataFrame") and not isinstance(pd.DataFrame, type(object)):
        df_chain = pd.DataFrame(option_chain)
        if spot > 0:
            if "expiration" not in df_chain.columns and "expiry" in df_chain.columns:
                df_chain["expiration"] = df_chain["expiry"]
            df_chain = fill_missing_mid_with_parity(df_chain, spot=spot)
            option_chain = df_chain.to_dict(orient="records")
    return option_chain


def filter_expiries_by_dte(
    expiries: Sequence[str], dte_range: Sequence[int] | None
) -> List[str]:
    """Return expiries whose DTE lies within ``dte_range``."""

    if not dte_range:
        return list(expiries)
    filtered: List[str] = []
    for exp in expiries:
        dte = _dte(exp)
        if dte is not None and dte_range[0] <= dte <= dte_range[1]:
            filtered.append(exp)
    return filtered


def generate_short_vertical(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
    *,
    strategy_name: "StrategyName",
    option_type: str,
    delta_range_key: str,
) -> tuple[List["StrategyProposal"], list[str]]:
    """Shared generator for short vertical call and put spreads."""

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

    rules = config.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    if spot is None:
        raise ValueError("spot price is required")

    option_chain = prepare_option_chain(option_chain, spot)
    expiries = sorted({str(o.get("expiry")) for o in option_chain})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    strike_map = _build_strike_map(option_chain)

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    delta_range = rules.get(delta_range_key) or []
    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")
    dte_range = rules.get("dte_range")

    expiries = filter_expiries_by_dte(expiries, dte_range)

    leg_right = "call" if option_type == "C" else "put"

    if len(delta_range) == 2 and (target_delta is not None or atr_mult is not None):
        for expiry in expiries:
            short_opt = None
            for opt in option_chain:
                if (
                    str(opt.get("expiry")) == expiry
                    and get_leg_right(opt) == leg_right
                    and opt.get("delta") is not None
                    and delta_range[0] <= float(opt.get("delta")) <= delta_range[1]
                ):
                    short_opt = opt
                    break
            if not short_opt:
                reason = "short optie ontbreekt"
                desc = (
                    f"target_delta {target_delta}" if target_delta is not None else f"atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry}],
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
                expiry=expiry,
                option_type=option_type,
            )
            if width is None:
                reason = "breedte niet berekend"
                desc = (
                    f"target_delta {target_delta}" if target_delta is not None else f"atr_mult {atr_mult}"
                )
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[
                        {
                            "expiry": expiry,
                            "strike": short_opt.get("strike"),
                            "type": option_type,
                            "position": -1,
                        }
                    ],
                )
                rejected_reasons.append(reason)
                continue
            if option_type == "C":
                long_strike_target = float(short_opt.get("strike")) + width
            else:
                long_strike_target = float(short_opt.get("strike")) - width
            long_strike = _nearest_strike(strike_map, expiry, option_type, long_strike_target)
            desc = f"short {short_opt.get('strike')} long {long_strike.matched}"
            legs_info = [
                {
                    "expiry": expiry,
                    "strike": short_opt.get("strike"),
                    "type": option_type,
                    "position": -1,
                },
                {
                    "expiry": expiry,
                    "strike": long_strike.matched,
                    "type": option_type,
                    "position": 1,
                },
            ]
            if not long_strike.matched:
                reason = "long strike niet gevonden"
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=legs_info,
                )
                rejected_reasons.append(reason)
                continue
            long_opt = _find_option(option_chain, expiry, long_strike.matched, option_type)
            if not long_opt:
                reason = "long optie ontbreekt"
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=legs_info,
                )
                rejected_reasons.append(reason)
                continue
            legs = [
                build_leg({**short_opt, "spot": spot}, "short"),
                build_leg({**long_opt, "spot": spot}, "long"),
            ]
            proposal = StrategyProposal(legs=legs)
            score, reasons = calculate_score(strategy_name, proposal, spot)
            if score is not None and passes_risk(proposal, min_rr):
                proposals.append(proposal)
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    proposal.__dict__,
                    "pass",
                    "criteria",
                    legs=legs,
                )
            else:
                reason = "; ".join(reasons) if reasons else "risk/reward onvoldoende"
                log_combo_evaluation(
                    strategy_name,
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
            if reached_limit(proposals):
                break
    else:
        rejected_reasons.append("ongeldige delta range")

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))


__all__ = [
    "MAX_PROPOSALS",
    "reached_limit",
    "validate_width_list",
    "compute_dynamic_width",
    "prepare_option_chain",
    "filter_expiries_by_dte",
    "generate_short_vertical",
]

