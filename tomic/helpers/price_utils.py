from __future__ import annotations
"""Price-related helper utilities."""

from tomic.logutils import logger
from tomic.utils import load_price_history


def _load_latest_close(symbol: str) -> tuple[float | None, str | None]:
    """Return the most recent close and its date for ``symbol``."""
    logger.debug(f"Loading close price for {symbol}")
    data = load_price_history(symbol)
    if data:
        rec = data[-1]
        try:
            price = float(rec.get("close"))
            date_str = str(rec.get("date"))
            if price <= 0:
                logger.debug(
                    f"Ignoring non-positive close for {symbol} on {date_str}: {price}"
                )
                return None, date_str
            logger.debug(f"Using last close for {symbol} on {date_str}: {price}")
            return price, date_str
        except Exception:
            return None, None
    return None, None


__all__ = ["_load_latest_close"]
