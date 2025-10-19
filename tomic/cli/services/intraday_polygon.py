from __future__ import annotations

"""Services for fetching intraday Polygon prices."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import Sequence
from zoneinfo import ZoneInfo

from tomic.config import get as cfg_get
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.infrastructure.throttling import RateLimiter
from tomic.integrations.polygon.client import PolygonClient
from tomic.logutils import logger
from tomic.polygon_prices import request_intraday, store_record


def fetch_polygon_intraday_prices(symbols: Sequence[str] | None = None) -> list[str]:
    """Fetch intraday Polygon prices for ``symbols``."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    if not target_symbols:
        logger.warning("No symbols configured for Polygon intraday fetch")
        return []

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    limiter = RateLimiter(1, 0.1, sleep=sleep)
    client = PolygonClient()
    client.connect()
    stored: list[str] = []
    try:
        for sym in target_symbols:
            limiter.wait()
            record = request_intraday(client, sym)
            if not record:
                logger.warning(f"No intraday data for {sym}")
                continue
            file = base_dir / f"{sym}.json"
            store_record(file, record)
            stored.append(sym)
            meta = load_price_meta()
            meta[f"intraday_{sym}"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
            save_price_meta(meta)
    finally:
        client.disconnect()

    if stored:
        logger.success(f"✅ Intraday prijzen opgeslagen voor {len(stored)} symbolen")
    else:
        logger.warning("⚠️ Geen intraday Polygon-prijzen opgeslagen")
    return stored
