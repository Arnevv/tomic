"""Utility helpers for strategy modules."""

from __future__ import annotations

import math
from typing import Sequence, Any, Dict, List, Mapping

import pandas as pd
from tomic.helpers.put_call_parity import fill_missing_mid_with_parity
from tomic.helpers.dateutils import dte_between_dates, filter_by_dte

from . import StrategyName
from ..utils import normalize_right, get_leg_right, today


def _reason_messages(reasons: Sequence[Any]) -> list[str]:
    return [getattr(reason, "message", str(reason)) for reason in reasons]
from ..logutils import logger


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


def compute_sigma_width(short_opt: Dict[str, Any], *, spot: float, sigma_multiple: float) -> float | None:
    """Return width based on a one-sigma move."""

    try:
        iv = float(short_opt.get("iv"))
        exp = str(short_opt.get("expiry"))
        dte = dte_between_dates(today(), exp)
        return spot * sigma_multiple * iv * math.sqrt(max(dte, 0) / 365)
    except Exception:
        return None


def compute_delta_width(
    short_opt: Dict[str, Any],
    *,
    target_delta: float,
    option_chain: List[Dict[str, Any]],
    expiry: str,
    option_type: str,
) -> float | None:
    """Return width based on the distance to a target delta option."""

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


def compute_atr_width(*, atr: float, atr_multiple: float, use_atr: bool) -> float | None:
    """Return width based on an ATR multiple."""

    try:
        width = atr_multiple * (atr if use_atr else 1.0)
        return abs(width)
    except Exception:
        return None


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
        return compute_sigma_width(short_opt, spot=spot, sigma_multiple=sigma_multiple)

    if target_delta is not None and option_chain and expiry and option_type:
        return compute_delta_width(
            short_opt,
            target_delta=target_delta,
            option_chain=option_chain,
            expiry=expiry,
            option_type=option_type,
        )

    if atr_multiple is not None and atr is not None:
        return compute_atr_width(atr=atr, atr_multiple=atr_multiple, use_atr=use_atr)

    return None


def prepare_option_chain(option_chain: List[Dict[str, Any]], spot: float) -> List[Dict[str, Any]]:
    """Return ``option_chain`` as list of dicts with parity-filled mids."""

    if hasattr(pd, "DataFrame") and isinstance(pd.DataFrame, type):
        try:
            df_chain = pd.DataFrame(option_chain)
        except TypeError:
            return option_chain
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
    return filter_by_dte(expiries, lambda exp: exp, (dte_range[0], dte_range[1]))


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

    from ..utils import build_leg
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
    strike_map = _build_strike_map(option_chain)

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")

    leg_right = "call" if option_type == "C" else "put"

    tol_value = rules.get("long_wing_strike_tolerance_percent")
    long_wing_tolerance = float(tol_value) if tol_value is not None else 5.0

    strat_label = getattr(strategy_name, "value", strategy_name)
    if strat_label in {
        StrategyName.SHORT_CALL_SPREAD.value,
        StrategyName.SHORT_PUT_SPREAD.value,
    }:
        logger.info(f"[{strat_label}] short=market/parity, long=fallback ok")

    if target_delta is not None or atr_mult is not None:
        candidates = [
            opt
            for opt in option_chain
            if get_leg_right(opt) == leg_right and opt.get("expiry") is not None
        ]
        if not candidates:
            rejected_reasons.append("short optie ontbreekt")
        for short_opt in candidates:
            expiry = str(short_opt.get("expiry"))
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
            long_strike = _nearest_strike(
                strike_map,
                expiry,
                option_type,
                long_strike_target,
                tolerance_percent=long_wing_tolerance,
            )
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
            proposal = StrategyProposal(strategy=str(strategy_name), legs=legs)
            score, reasons = calculate_score(strategy_name, proposal, spot, atr=atr)
            reason_messages = _reason_messages(reasons)
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
                reason = "; ".join(reason_messages) if reason_messages else "risk/reward onvoldoende"
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    proposal.__dict__,
                    "reject",
                    reason,
                    legs=legs,
                )
                if reason_messages:
                    rejected_reasons.extend(reason_messages)
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


def generate_wing_spread(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
    *,
    strategy_name: "StrategyName",
    centers: Sequence[float] | None = None,
    call_range: Sequence[float] | None = None,
    put_range: Sequence[float] | None = None,
    score_func=None,
) -> tuple[List["StrategyProposal"], list[str]]:
    """Generate iron condor or ATM iron butterfly proposals.

    Parameters
    ----------
    strategy_name:
        Calling strategy name used for logging and scoring.
    centers:
        List of center strike offsets from spot. When provided a butterfly is
        generated using the same strike for the short call and put. Offsets are
        interpreted as absolute values unless ``use_ATR`` is enabled.
    call_range, put_range:
        Delta ranges for the short call and put. When both provided an iron
        condor is generated with separate short legs.
    """

    from itertools import islice
    from ..utils import build_leg
    from ..analysis.scoring import calculate_score as _calculate_score, passes_risk
    from ..logutils import log_combo_evaluation
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
    expiries = sorted({str(o.get("expiry")) for o in option_chain if o.get("expiry") is not None})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    strike_map = _build_strike_map(option_chain)

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    sigma_mult = float(rules.get("wing_sigma_multiple", 1.0))
    strat_label = getattr(strategy_name, "value", strategy_name)
    long_wing_tolerance = None
    long_wing_tolerance_val = rules.get("long_wing_strike_tolerance_percent")
    if long_wing_tolerance_val is not None:
        long_wing_tolerance = float(long_wing_tolerance_val)
    elif strat_label in {
        StrategyName.IRON_CONDOR.value,
        StrategyName.ATM_IRON_BUTTERFLY.value,
    }:
        long_wing_tolerance = 5.0

    if strat_label == StrategyName.IRON_CONDOR.value:
        logger.info(
            "[iron_condor] short legs: parity ok; long legs: fallback permitted (max 2)"
        )
    if strat_label == StrategyName.ATM_IRON_BUTTERFLY.value:
        logger.info(
            "[atm_iron_butterfly] short legs: parity ok; long legs: fallback permitted (max 2)"
        )

    # Butterfly mode when centers are provided
    if centers is not None:
        for expiry in expiries:
            if reached_limit(proposals):
                break
            for c_off in centers:
                center = spot + (c_off * atr if use_atr else c_off)
                center = _nearest_strike(strike_map, expiry, "C", center).matched
                desc_base = f"center {center}"
                if center is None:
                    reason = "center strike niet gevonden"
                    log_combo_evaluation(
                        strategy_name,
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
                        strategy_name,
                        desc_base,
                        None,
                        "reject",
                        reason,
                        legs=[
                            {"expiry": expiry, "strike": center, "type": "C", "position": -1},
                            {"expiry": expiry, "strike": center, "type": "P", "position": -1},
                        ],
                    )
                    rejected_reasons.append(reason)
                    continue
                width = compute_dynamic_width(sc_opt, spot=spot, sigma_multiple=sigma_mult)
                if width is None:
                    reason = "breedte niet berekend"
                    log_combo_evaluation(
                        strategy_name,
                        desc_base,
                        None,
                        "reject",
                        reason,
                        legs=[
                            {"expiry": expiry, "strike": center, "type": "C", "position": -1},
                            {"expiry": expiry, "strike": center, "type": "P", "position": -1},
                        ],
                    )
                    rejected_reasons.append(reason)
                    continue
                sc_strike = sp_strike = center
                lc = _nearest_strike(
                    strike_map,
                    expiry,
                    "C",
                    center + width,
                    tolerance_percent=long_wing_tolerance,
                )
                lp = _nearest_strike(
                    strike_map,
                    expiry,
                    "P",
                    center - width,
                    tolerance_percent=long_wing_tolerance,
                )
                lc_strike = lc.matched
                lp_strike = lp.matched
                desc = f"center {center} sigma {sigma_mult}"
                base_legs = [
                    {"expiry": expiry, "strike": sc_strike, "type": "C", "position": -1},
                    {"expiry": expiry, "strike": sp_strike, "type": "P", "position": -1},
                    {"expiry": expiry, "strike": lc_strike, "type": "C", "position": 1},
                    {"expiry": expiry, "strike": lp_strike, "type": "P", "position": 1},
                ]
                if not all([sc_strike, sp_strike, lc_strike, lp_strike]):
                    reason = "ontbrekende strikes"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=base_legs
                    )
                    rejected_reasons.append(reason)
                    continue
                lc_opt = _find_option(option_chain, expiry, lc_strike, "C")
                lp_opt = _find_option(option_chain, expiry, lp_strike, "P")
                if not all([lc_opt, lp_opt]):
                    reason = "opties niet gevonden"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=base_legs
                    )
                    rejected_reasons.append(reason)
                    continue
                legs = [
                    build_leg({**sc_opt, "spot": spot}, "short"),
                    build_leg({**lc_opt, "spot": spot}, "long"),
                    build_leg({**sp_opt, "spot": spot}, "short"),
                    build_leg({**lp_opt, "spot": spot}, "long"),
                ]
                proposal = StrategyProposal(strategy=str(strategy_name), legs=legs)
                score, reasons = (score_func or _calculate_score)(
                    strategy_name, proposal, spot, atr=atr
                )
                reason_messages = _reason_messages(reasons)
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
                    reason = "; ".join(reason_messages) if reason_messages else "risk/reward onvoldoende"
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    if reason_messages:
                        rejected_reasons.extend(reason_messages)
                    else:
                        rejected_reasons.append("risk/reward onvoldoende")
                if reached_limit(proposals):
                    break
            if reached_limit(proposals):
                break
    else:
        # Condor mode
        for expiry in expiries:
            if reached_limit(proposals):
                break
            shorts_c = [
                o
                for o in option_chain
                if str(o.get("expiry")) == expiry and get_leg_right(o) == "call"
            ]
            shorts_p = [
                o
                for o in option_chain
                if str(o.get("expiry")) == expiry and get_leg_right(o) == "put"
            ]
            if not shorts_c or not shorts_p:
                reason = "short optie ontbreekt"
                log_combo_evaluation(
                    strategy_name,
                    "delta scan",
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": expiry}],
                )
                rejected_reasons.append(reason)
                continue
            for sc_opt, sp_opt in islice(zip(shorts_c, shorts_p), MAX_PROPOSALS):
                sc_strike = float(sc_opt.get("strike"))
                sp_strike = float(sp_opt.get("strike"))
                sc = _nearest_strike(strike_map, expiry, "C", sc_strike)
                sp = _nearest_strike(strike_map, expiry, "P", sp_strike)
                desc = f"SC {sc.matched} SP {sp.matched} σ {sigma_mult}"
                base_legs = [
                    {"expiry": expiry, "strike": sc_strike, "type": "C", "position": -1},
                    {"expiry": expiry, "strike": sp_strike, "type": "P", "position": -1},
                ]
                if not sc.matched or not sp.matched:
                    reason = "ontbrekende strikes"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=base_legs
                    )
                    rejected_reasons.append(reason)
                    continue
                c_w = compute_dynamic_width(sc_opt, spot=spot, sigma_multiple=sigma_mult)
                p_w = compute_dynamic_width(sp_opt, spot=spot, sigma_multiple=sigma_mult)
                if c_w is None or p_w is None:
                    reason = "breedte niet berekend"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=base_legs
                    )
                    rejected_reasons.append(reason)
                    continue
                lc_target = sc_strike + c_w
                lp_target = sp_strike - p_w
                lc = _nearest_strike(
                    strike_map,
                    expiry,
                    "C",
                    lc_target,
                    tolerance_percent=long_wing_tolerance,
                )
                lp = _nearest_strike(
                    strike_map,
                    expiry,
                    "P",
                    lp_target,
                    tolerance_percent=long_wing_tolerance,
                )
                long_leg_info = [
                    {"expiry": expiry, "strike": lc.matched, "type": "C", "position": 1},
                    {"expiry": expiry, "strike": lp.matched, "type": "P", "position": 1},
                ]
                if not all([lc.matched, lp.matched]):
                    reason = "ontbrekende strikes"
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        None,
                        "reject",
                        reason,
                        legs=base_legs + long_leg_info,
                    )
                    rejected_reasons.append(reason)
                    continue
                lc_opt = _find_option(option_chain, expiry, lc.matched, "C")
                lp_opt = _find_option(option_chain, expiry, lp.matched, "P")
                if not all([lc_opt, lp_opt]):
                    reason = "opties niet gevonden"
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        None,
                        "reject",
                        reason,
                        legs=base_legs + long_leg_info,
                    )
                    rejected_reasons.append(reason)
                    continue
                legs = [
                    build_leg({**sc_opt, "spot": spot}, "short"),
                    build_leg({**lc_opt, "spot": spot}, "long"),
                    build_leg({**sp_opt, "spot": spot}, "short"),
                    build_leg({**lp_opt, "spot": spot}, "long"),
                ]
                proposal = StrategyProposal(strategy=str(strategy_name), legs=legs)
                score, reasons = (score_func or _calculate_score)(
                    strategy_name, proposal, spot, atr=atr
                )
                reason_messages = _reason_messages(reasons)
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
                    reason = "; ".join(reason_messages) if reason_messages else "risk/reward onvoldoende"
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    if reason_messages:
                        rejected_reasons.extend(reason_messages)
                    else:
                        rejected_reasons.append("risk/reward onvoldoende")
                if reached_limit(proposals):
                    break

    proposals.sort(key=lambda p: p.score or 0, reverse=True)
    if not proposals:
        return [], sorted(set(rejected_reasons))
    return proposals[:MAX_PROPOSALS], sorted(set(rejected_reasons))


def generate_ratio_like(
    symbol: str,
    option_chain: List[Dict[str, Any]],
    config: Dict[str, Any],
    spot: float,
    atr: float,
    *,
    strategy_name: "StrategyName",
    option_type: str,
    delta_range_key: str,
    use_expiry_pairs: bool,
    max_pairs: int | None = None,
) -> tuple[List["StrategyProposal"], list[str]]:
    """Generator shared by ratio-like strategies.

    Parameters
    ----------
    strategy_name:
        Name of the calling strategy.
    option_type:
        ``"C"`` for call based strategies or ``"P"`` for put based.
    delta_range_key:
        Configuration key locating the short leg delta range.
    use_expiry_pairs:
        When ``True`` the long leg is placed in a later expiry.
    max_pairs:
        Optional limit of expiry pairs to evaluate.
    """

    from ..utils import build_leg
    from ..analysis.scoring import calculate_score, passes_risk
    from ..logutils import log_combo_evaluation
    from ..strategy_candidates import (
        StrategyProposal,
        _build_strike_map,
        _nearest_strike,
        _find_option,
        _validate_ratio,
        select_expiry_pairs,
    )

    rules = config.get("strike_to_strategy_config", {})
    use_atr = bool(rules.get("use_ATR"))
    if spot is None:
        raise ValueError("spot price is required")

    option_chain = prepare_option_chain(option_chain, spot)
    expiries = sorted({str(o.get("expiry")) for o in option_chain if o.get("expiry") is not None})
    if not expiries:
        return [], ["geen expiraties beschikbaar"]
    strike_map = _build_strike_map(option_chain)

    proposals: List[StrategyProposal] = []
    rejected_reasons: list[str] = []
    min_rr = float(config.get("min_risk_reward", 0.0))

    target_delta = rules.get("long_leg_distance_points")
    atr_mult = rules.get("long_leg_atr_multiple")

    if use_expiry_pairs:
        min_gap = int(rules.get("expiry_gap_min_days", 0))
        pairs = select_expiry_pairs(expiries, min_gap)
        if max_pairs is not None:
            pairs = pairs[:max_pairs]
    else:
        pairs = [(exp, exp) for exp in expiries]

    leg_right = "call" if option_type == "C" else "put"

    tol_value = rules.get("long_wing_strike_tolerance_percent")
    long_wing_tolerance = float(tol_value) if tol_value is not None else 5.0

    strat_label = getattr(strategy_name, "value", strategy_name)
    if strat_label in {
        StrategyName.RATIO_SPREAD.value,
        StrategyName.BACKSPREAD_PUT.value,
    }:
        logger.info(
            f"[{strat_label}] short legs: parity ok; long legs: fallback permitted (max 2)"
        )

    if target_delta is not None or atr_mult is not None:
        for short_exp, long_exp in pairs:
            candidates = [
                opt
                for opt in option_chain
                if str(opt.get("expiry")) == short_exp and get_leg_right(opt) == leg_right
            ]
            if not candidates:
                reason = "short optie ontbreekt"
                desc = (
                    f"near {short_exp} far {long_exp}" if short_exp != long_exp else f"expiry {short_exp}"
                )
                log_combo_evaluation(
                    strategy_name,
                    desc,
                    None,
                    "reject",
                    reason,
                    legs=[{"expiry": short_exp}],
                )
                rejected_reasons.append(reason)
                continue

            for short_opt in candidates:
                width = compute_dynamic_width(
                    short_opt,
                    target_delta=target_delta,
                    atr_multiple=atr_mult,
                    atr=atr,
                    use_atr=use_atr,
                    option_chain=option_chain,
                    expiry=long_exp,
                    option_type=option_type,
                )
                if width is None:
                    reason = "breedte niet berekend"
                    desc = (
                        f"near {short_exp} far {long_exp}"
                        if short_exp != long_exp
                        else f"expiry {short_exp}"
                    )
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        None,
                        "reject",
                        reason,
                        legs=[
                            {
                                "expiry": short_exp,
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
                long_strike = _nearest_strike(
                    strike_map,
                    long_exp,
                    option_type,
                    long_strike_target,
                    tolerance_percent=long_wing_tolerance,
                )
                desc_base = (
                    f"near {short_exp} far {long_exp} " if short_exp != long_exp else ""
                )
                desc = f"{desc_base}short {short_opt.get('strike')} long {long_strike.matched}"
                legs_info = [
                    {
                        "expiry": short_exp,
                        "strike": short_opt.get("strike"),
                        "type": option_type,
                        "position": -1,
                    },
                    {
                        "expiry": long_exp,
                        "strike": long_strike.matched,
                        "type": option_type,
                        "position": 2,
                    },
                ]
                if not long_strike.matched:
                    reason = "long strike niet gevonden"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=legs_info
                    )
                    rejected_reasons.append(reason)
                    continue

                long_opt = _find_option(option_chain, long_exp, long_strike.matched, option_type)
                if not long_opt:
                    reason = "long optie ontbreekt"
                    log_combo_evaluation(
                        strategy_name, desc, None, "reject", reason, legs=legs_info
                    )
                    rejected_reasons.append(reason)
                    continue

                legs = [
                    build_leg({**short_opt, "spot": spot}, "short"),
                    build_leg({**long_opt, "spot": spot}, "long"),
                ]
                legs[1]["position"] = 2
                proposal = StrategyProposal(strategy=str(strategy_name), legs=legs)
                score, reasons = calculate_score(strategy_name, proposal, spot, atr=atr)
                reason_messages = _reason_messages(reasons)
                if score is not None and passes_risk(proposal, min_rr):
                    if _validate_ratio(strategy_name.value, legs, proposal.credit or 0.0):
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
                        reason = "verkeerde ratio"
                        log_combo_evaluation(
                            strategy_name,
                            desc,
                            proposal.__dict__,
                            "reject",
                            reason,
                            legs=legs,
                        )
                        rejected_reasons.append(reason)
                else:
                    reason = "; ".join(reason_messages) if reason_messages else "risk/reward onvoldoende"
                    log_combo_evaluation(
                        strategy_name,
                        desc,
                        proposal.__dict__,
                        "reject",
                        reason,
                        legs=legs,
                    )
                    if reason_messages:
                        rejected_reasons.extend(reason_messages)
                    else:
                        rejected_reasons.append("risk/reward onvoldoende")
                if reached_limit(proposals):
                    break
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
    "compute_sigma_width",
    "compute_delta_width",
    "compute_atr_width",
    "compute_dynamic_width",
    "prepare_option_chain",
    "filter_expiries_by_dte",
    "generate_short_vertical",
    "generate_wing_spread",
    "generate_ratio_like",
]

