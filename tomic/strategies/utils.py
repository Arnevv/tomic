"""Utility helpers for strategy modules."""

from __future__ import annotations

import math
from typing import Sequence, Any, Dict, List, Mapping

from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today

from ..logutils import logger


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
        candidates = [
            o
            for o in option_chain
            if str(o.get("expiry")) == expiry
            and (o.get("type") or o.get("right")) == option_type
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


__all__ = ["validate_width_list", "compute_dynamic_width"]

