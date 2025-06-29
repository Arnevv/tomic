from __future__ import annotations

"""Fetch daily price history using the Polygon API."""

from datetime import datetime, timedelta
from pathlib import Path
from time import sleep
from typing import Iterable, List

from tomic.analysis.metrics import average_true_range

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import update_json_file
from tomic.polygon_client import PolygonClient
from .compute_volstats_polygon import main as compute_volstats_polygon_main


def _request_bars(client: PolygonClient, symbol: str) -> Iterable[dict]:
    """Return daily bar records for ``symbol`` using Polygon."""
    today = datetime.now().date()
    start = today - timedelta(days=365)
    path = f"v2/aggs/ticker/{symbol}/range/1/day/{start}/{today}"
    data = client._request(path, {"limit": 252, "adjusted": "true"})
    bars = data.get("results") or []
    records = []
    for bar in bars:
        try:
            ts = int(bar.get("t")) / 1000
            dt = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
            records.append(
                {
                    "symbol": symbol,
                    "date": dt,
                    "open": bar.get("o"),
                    "high": bar.get("h"),
                    "low": bar.get("l"),
                    "close": bar.get("c"),
                    "volume": bar.get("v"),
                    "atr": None,
                }
            )
        except Exception as exc:  # pragma: no cover - malformed data
            logger.debug(f"Skipping malformed bar for {symbol}: {exc}")

    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for rec in records:
        highs.append(rec.get("high"))
        lows.append(rec.get("low"))
        closes.append(rec.get("close"))
        rec["atr"] = average_true_range(highs, lows, closes, period=14)
        rec.pop("open", None)
        rec.pop("high", None)
        rec.pop("low", None)
    return records


def main(argv: List[str] | None = None) -> None:
    """Fetch price history for default or provided symbols via Polygon."""
    setup_logging()
    logger.info("🚀 Price history fetch via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored = 0
    try:
        for idx, sym in enumerate(symbols):
            logger.info(f"Fetching bars for {sym}")
            records = list(_request_bars(client, sym))
            if not records:
                logger.warning(f"No price data for {sym}")
            else:
                file = base_dir / f"{sym}.json"
                for rec in records:
                    update_json_file(file, rec, ["date"])
                stored += 1
    finally:
        client.disconnect()
    logger.success(f"✅ Historische prijzen opgeslagen voor {stored} symbolen")

    compute_volstats_polygon_main(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
