from __future__ import annotations

"""Fetch daily price history using the Polygon API."""

print("🚀 Script bootstrap start")  # stdout fallback

from datetime import datetime
from pathlib import Path
from time import sleep
import time
from typing import List
from zoneinfo import ZoneInfo

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.integrations.polygon.client import PolygonClient
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from .compute_volstats_polygon import main as compute_volstats_polygon_main
from tomic.polygon_prices import request_bars, merge_price_data


def main(argv: List[str] | None = None) -> None:
    """Fetch price history for default or provided symbols via Polygon."""
    setup_logging()
    logger.info("🚀 Price history fetch via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]
    raw_max = cfg_get("MAX_SYMBOLS_PER_RUN")
    try:
        max_syms = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_syms = None
    sleep_between = float(cfg_get("POLYGON_SLEEP_BETWEEN", 1.2))
    max_per_minute = int(cfg_get("POLYGON_REQUESTS_PER_MINUTE", 5))

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored = 0
    processed: list[str] = []
    request_times: list[float] = []
    try:
        for idx, sym in enumerate(symbols):
            if max_syms is not None and idx >= max_syms:
                break
            now = time.time()
            request_times = [t for t in request_times if now - t < 60]
            if len(request_times) >= max_per_minute:
                wait = 60 - (now - request_times[0])
                if wait > 0:
                    logger.info(
                        f"⌛ Rate limit: sleeping {wait:.1f}s to stay under {max_per_minute}/min"
                    )
                    time.sleep(wait)
                    request_times = [t for t in request_times if now - t < 60]
            request_times.append(time.time())

            records, requested = request_bars(client, sym)
            if not records:
                continue
            file = base_dir / f"{sym}.json"
            merge_price_data(file, records)
            stored += 1
            processed.append(sym)
            meta = load_price_meta()
            meta[f"day_{sym}"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
            save_price_meta(meta)
            if requested:
                sleep(sleep_between)
    finally:
        client.disconnect()
    logger.success(f"✅ Historische prijzen opgeslagen voor {stored} symbolen")

    # Immediately compute volatility statistics for the fetched symbols
    compute_volstats_polygon_main(processed)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
