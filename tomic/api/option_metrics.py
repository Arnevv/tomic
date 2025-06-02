"""Fetch option metrics for a single contract."""

from __future__ import annotations

from typing import Any, Dict

from tomic.api.market_export import _await_market_data, _start_app
from tomic.api.combined_app import CombinedApp
from tomic.logging import logger


def fetch_option_metrics(
    symbol: str, expiry: str, strike: float, right: str
) -> Dict[str, Any] | None:
    """Return spot price, volume and open interest for a single option.

    ``expiry`` must be ``YYYY-MM-DD`` and ``right`` either ``C`` or ``P``.
    ``strike`` is parsed as a float.
    """

    expiry = expiry.replace("-", "")
    right = right.upper()
    if right not in {"C", "P"}:
        raise ValueError("right must be 'C' or 'P'")
    app = CombinedApp(symbol)
    _start_app(app)
    if not _await_market_data(app, symbol):
        app.disconnect()
        return None

    records = [
        data
        for req_id, data in app.market_data.items()
        if req_id not in app.invalid_contracts
        and data.get("expiry") == expiry
        and data.get("strike") == strike
        and data.get("right") == right
    ]

    if not records:
        app.disconnect()
        logger.warning("Geen overeenkomstige optie gevonden")
        return None

    spot = app.spot_price
    volume = sum(r.get("volume", 0) or 0 for r in records)
    open_interest = sum(r.get("open_interest", 0) or 0 for r in records)

    app.disconnect()
    logger.info(
        f"Data voor {symbol} {expiry} {strike} {right}: spot={spot}, volume={volume}, OI={open_interest}"
    )
    return {"spot_price": spot, "volume": volume, "open_interest": open_interest}


__all__ = ["fetch_option_metrics"]
