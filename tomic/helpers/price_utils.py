from __future__ import annotations
"""Price-related helper utilities."""

from tomic.logutils import logger
from tomic.utils import load_price_history


def _load_latest_close(
    symbol: str, *, return_date_only: bool = False
) -> tuple[float | None, str | None] | str | None:
    """Return the most recent close and its date for ``symbol``.

    Parameters
    ----------
    symbol:
        The ticker symbol to look up.
    return_date_only:
        When ``True`` only the close date is returned.  Otherwise a tuple of
        ``(price, date)`` is returned as before.
    """

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
                return date_str if return_date_only else (None, date_str)
            logger.debug(f"Using last close for {symbol} on {date_str}: {price}")
            return date_str if return_date_only else (price, date_str)
        except Exception:
            return None if return_date_only else (None, None)
    return None if return_date_only else (None, None)


__all__ = ["_load_latest_close"]
