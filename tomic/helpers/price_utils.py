from __future__ import annotations
"""Price-related helper utilities."""

from pathlib import Path
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.journal.utils import load_json


def _load_latest_close(symbol: str) -> tuple[float | None, str | None]:
    """Return the most recent close and its date for ``symbol``."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    logger.debug(f"Loading close price for {symbol} from {path}")
    data = load_json(path)
    if isinstance(data, list) and data:
        data.sort(key=lambda r: r.get("date", ""))
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
