from __future__ import annotations

from typing import Any, Mapping, Literal, Optional, TypedDict

from tomic.bs_calculator import black_scholes
from tomic.helpers.dateutils import dte_between_dates
from tomic.helpers.timeutils import today
from tomic.config import get as cfg_get
from tomic.utils import get_option_mid_price, normalize_leg


class OptionLeg(TypedDict, total=False):
    """Normalized representation of an option leg used for strategy scoring."""

    expiry: Optional[str]
    type: Optional[str]
    strike: Optional[float]
    spot: Optional[float]
    iv: Optional[float]
    delta: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    model: Optional[float]
    edge: Optional[float]
    volume: Optional[float]
    open_interest: Optional[float]
    position: int
    mid_fallback: Optional[str]


def build_leg(quote: Mapping[str, Any], side: Literal["long", "short"]) -> OptionLeg:
    """Construct a normalized leg dictionary from an option quote.

    Parameters
    ----------
    quote:
        Option data containing bid/ask, greeks and other fields.
    side:
        ``"long"`` or ``"short"`` indicating the position.

    Returns
    -------
    OptionLeg
        The normalized leg information.
    """

    bid = quote.get("bid")
    ask = quote.get("ask")
    mid = get_option_mid_price(quote)
    used_close = False
    if mid is None:
        try:
            close_val = float(quote.get("close"))
            if close_val > 0:
                mid = close_val
                used_close = True
        except Exception:
            pass
    else:
        try:
            close_val = float(quote.get("close"))
            if mid == close_val:
                used_close = True
        except Exception:
            pass

    leg: OptionLeg = {
        "expiry": quote.get("expiry") or quote.get("expiration"),
        "type": quote.get("type") or quote.get("right"),
        "strike": quote.get("strike"),
        "spot": quote.get("spot")
        or quote.get("underlying_price")
        or quote.get("underlying"),
        "iv": quote.get("iv"),
        "delta": quote.get("delta"),
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "volume": quote.get("volume"),
        "open_interest": quote.get("open_interest"),
        "position": 1 if side == "long" else -1,
    }

    if quote.get("mid_from_parity"):
        leg["mid_fallback"] = "parity"
    elif used_close:
        leg["mid_fallback"] = "close"

    # Estimate model price when possible
    try:
        opt_type = (leg.get("type") or "").upper()[0]
        strike = float(leg["strike"]) if leg.get("strike") is not None else None
        iv = float(leg["iv"]) if leg.get("iv") is not None else None
        exp = leg.get("expiry")
        spot = float(leg["spot"]) if leg.get("spot") is not None else None
        if spot is not None and iv is not None and iv > 0 and exp and strike is not None:
            dte = dte_between_dates(today(), str(exp))
            r = float(cfg_get("INTEREST_RATE", 0.05))
            q = 0.0
            leg["model"] = black_scholes(opt_type, spot, strike, dte, iv, r=r, q=q)
    except Exception:
        pass

    if leg.get("edge") is None and leg.get("mid") is not None and leg.get("model") is not None:
        leg["edge"] = leg["model"] - leg["mid"]

    return normalize_leg(leg)  # type: ignore[return-value]


__all__ = ["OptionLeg", "build_leg"]
