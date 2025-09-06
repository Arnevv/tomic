"""Black-Scholes helper utilities."""
from __future__ import annotations

import math

from ..bs_calculator import black_scholes
from .dateutils import dte_between_dates
from ..config import get as cfg_get
from ..utils import today


def estimate_price_delta(leg: dict) -> tuple[float, float]:
    """Estimate model price and delta for a leg using Black-Scholes.

    Parameters
    ----------
    leg: dict
        Option leg containing ``type``/``right``, ``strike``, ``spot`` or
        underlying price, implied volatility and expiry information.

    Returns
    -------
    tuple[float, float]
        A tuple of ``(price, delta)``.
    """
    opt_type = (leg.get("type") or leg.get("right") or "").upper()[0]
    strike = float(leg.get("strike"))
    spot = float(
        leg.get("spot")
        or leg.get("underlying_price")
        or leg.get("underlying")
    )
    iv = float(leg.get("iv"))
    exp = leg.get("expiry") or leg.get("expiration")
    if not exp:
        raise ValueError("missing expiry")
    dte = dte_between_dates(today(), str(exp))
    if dte is None or dte <= 0 or iv <= 0 or spot <= 0:
        raise ValueError("invalid parameters")
    r = float(cfg_get("INTEREST_RATE", 0.05))
    price = black_scholes(opt_type, spot, strike, dte, iv, r=r, q=0.0)
    T = dte / 365.0
    d1 = (
        math.log(spot / strike) + (r - 0.0 + 0.5 * iv * iv) * T
    ) / (iv * math.sqrt(T))
    nd1 = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
    delta = nd1 if opt_type == "C" else nd1 - 1
    return price, delta


def populate_model_delta(leg: dict) -> dict:
    """Populate missing ``model`` price and ``delta`` using Black-Scholes.

    This mutates ``leg`` in-place, estimating a theoretical price and delta
    via :func:`estimate_price_delta` when either field is missing or has a
    false-y value (``0``, ``"0"`` or ``""``).

    Parameters
    ----------
    leg: dict
        Option leg information containing required fields for Black-Scholes.

    Returns
    -------
    dict
        The updated ``leg`` dictionary.
    """

    need_model = leg.get("model") in (None, 0, "0", "")
    need_delta = leg.get("delta") in (None, 0, "0", "")
    if not (need_model or need_delta):
        return leg
    try:
        price, delta = estimate_price_delta(leg)
    except Exception:
        return leg
    if need_model:
        leg["model"] = price
    if need_delta:
        leg["delta"] = delta
    return leg


__all__ = ["estimate_price_delta", "populate_model_delta"]
