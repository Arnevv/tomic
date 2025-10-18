from __future__ import annotations

"""Fetch today's intraday price using the Polygon API."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import List
from zoneinfo import ZoneInfo

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.integrations.polygon.client import PolygonClient
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.polygon_prices import request_intraday, store_record
from tomic.infrastructure.throttling import RateLimiter


def main(argv: List[str] | None = None) -> None:
    """Fetch intraday prices for default or provided symbols."""

    setup_logging()
    logger.info("🚀 Intraday price fetch via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    limiter = RateLimiter(1, 0.1, sleep=sleep)
    client = PolygonClient()
    client.connect()
    stored = 0
    try:
        for sym in symbols:
            limiter.wait()
            record = request_intraday(client, sym)
            if not record:
                logger.warning(f"No intraday data for {sym}")
                continue
            file = base_dir / f"{sym}.json"
            store_record(file, record)
            stored += 1
            meta = load_price_meta()
            meta[f"intraday_{sym}"] = datetime.now(
                ZoneInfo("America/New_York")
            ).isoformat()
            save_price_meta(meta)
    finally:
        client.disconnect()
    logger.success(f"✅ Intraday prijzen opgeslagen voor {stored} symbolen")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
