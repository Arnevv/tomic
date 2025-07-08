from __future__ import annotations

"""Fetch today's intraday price using the Polygon API."""

from datetime import datetime, date
from pathlib import Path
from time import sleep
from typing import List
from zoneinfo import ZoneInfo

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import load_json, save_json
from tomic.polygon_client import PolygonClient
from tomic.helpers.price_meta import load_price_meta, save_price_meta


def _request_intraday(client: PolygonClient, symbol: str) -> dict | None:
    """Return the latest intraday bar for ``symbol`` from Polygon."""

    today = date.today().strftime("%Y-%m-%d")
    path = f"v2/aggs/ticker/{symbol}/range/1/minute/{today}/{today}"
    params = {"adjusted": "true", "sort": "desc", "limit": 1}
    data = client._request(path, params)
    results = data.get("results") or []
    if not results:
        return None
    bar = results[0]
    ts = int(bar.get("t")) / 1000
    dt = datetime.utcfromtimestamp(ts)
    return {
        "symbol": symbol,
        "date": dt.strftime("%Y-%m-%d"),
        "close": bar.get("c"),
        "volume": bar.get("v"),
        "atr": None,
        "intraday": True,
    }


def _store_record(file: Path, record: dict) -> None:
    """Overwrite today's entry in ``file`` with ``record``."""

    data = load_json(file)
    if not isinstance(data, list):
        data = []
    data = [r for r in data if r.get("date") != record.get("date")]
    data.append(record)
    data.sort(key=lambda r: r.get("date", ""))
    save_json(data, file)


def main(argv: List[str] | None = None) -> None:
    """Fetch intraday prices for default or provided symbols."""

    setup_logging()
    logger.info("🚀 Intraday price fetch via Polygon")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored = 0
    try:
        for sym in symbols:
            record = _request_intraday(client, sym)
            if not record:
                logger.warning(f"No intraday data for {sym}")
                continue
            file = base_dir / f"{sym}.json"
            _store_record(file, record)
            stored += 1
            meta = load_price_meta()
            meta[sym] = datetime.now(ZoneInfo("America/New_York")).isoformat()
            save_price_meta(meta)
            sleep(0.1)
    finally:
        client.disconnect()
    logger.success(f"✅ Intraday prijzen opgeslagen voor {stored} symbolen")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
