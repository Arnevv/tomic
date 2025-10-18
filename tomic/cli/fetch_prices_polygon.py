from __future__ import annotations

"""Fetch daily price history using the Polygon API."""

print("🚀 Script bootstrap start")  # stdout fallback

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import List
from zoneinfo import ZoneInfo

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.integrations.polygon.client import PolygonClient
from tomic.helpers.price_meta import load_price_meta, save_price_meta
from tomic.infrastructure.throttling import RateLimiter
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

    per_minute_limiter = RateLimiter(
        max_per_minute,
        60.0,
        sleep=sleep,
    )
    between_limiter = RateLimiter(
        1,
        sleep_between,
        sleep=sleep,
    )

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored = 0
    processed: list[str] = []
    previous_requested = False
    try:
        for idx, sym in enumerate(symbols):
            if max_syms is not None and idx >= max_syms:
                break
            if previous_requested:
                between_limiter.wait()
            delay = per_minute_limiter.time_until_ready()
            if delay > 0:
                logger.info(
                    f"⌛ Rate limit: sleeping {delay:.1f}s to stay under {max_per_minute}/min"
                )
                sleep(delay)

            records, requested = request_bars(client, sym)
            if not records:
                previous_requested = requested
                if requested:
                    per_minute_limiter.record()
                    between_limiter.record()
                continue
            file = base_dir / f"{sym}.json"
            merge_price_data(file, records)
            stored += 1
            processed.append(sym)
            meta = load_price_meta()
            meta[f"day_{sym}"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
            save_price_meta(meta)
            if requested:
                per_minute_limiter.record()
                between_limiter.record()
            previous_requested = requested
    finally:
        client.disconnect()
    logger.success(f"✅ Historische prijzen opgeslagen voor {stored} symbolen")

    # Immediately compute volatility statistics for the fetched symbols
    compute_volstats_polygon_main(processed)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
