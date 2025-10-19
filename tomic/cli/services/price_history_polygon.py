from __future__ import annotations

"""Services for fetching historical prices via Polygon."""

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
from tomic.polygon_prices import merge_price_data, request_bars

from .volatility import compute_polygon_volatility_stats


def fetch_polygon_price_history(symbols: Sequence[str] | None = None, *, run_volstats: bool = True) -> list[str]:
    """Fetch Polygon daily history for provided ``symbols``."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    if not target_symbols:
        logger.warning("No symbols configured for Polygon price fetch")
        return []

    raw_max = cfg_get("MAX_SYMBOLS_PER_RUN")
    try:
        max_syms = int(raw_max) if raw_max is not None else None
    except (TypeError, ValueError):
        max_syms = None
    sleep_between = float(cfg_get("POLYGON_SLEEP_BETWEEN", 1.2))
    max_per_minute = int(cfg_get("POLYGON_REQUESTS_PER_MINUTE", 5))

    per_minute_limiter = RateLimiter(max_per_minute, 60.0, sleep=sleep)
    between_limiter = RateLimiter(1, sleep_between, sleep=sleep)

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored: list[str] = []
    processed: list[str] = []
    previous_requested = False
    try:
        for idx, sym in enumerate(target_symbols):
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
            stored.append(sym)
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

    if stored:
        logger.success(f"✅ Historische prijzen opgeslagen voor {len(stored)} symbolen")
    else:
        logger.warning("⚠️ Geen historische Polygon-prijzen opgeslagen")

    if run_volstats and processed:
        compute_polygon_volatility_stats(processed)
    return processed
