from __future__ import annotations

"""Fetch the last 504 days of daily price history for configured symbols."""

from datetime import datetime, timezone
from types import MethodType
import threading
from typing import Iterable, List
from pathlib import Path

from ibapi.contract import Contract

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.api.ib_connection import connect_ib
from tomic.journal.utils import update_json_file
from .compute_volstats import main as compute_volstats_main


def _format_date(raw: str) -> str:
    """Convert ``YYYYMMDD`` strings to ``YYYY-MM-DD``."""
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


def _request_bars(app, symbol: str) -> Iterable[dict]:
    """Request daily bars for ``symbol`` and return ``PriceRecord`` objects."""
    app.historical_data = []
    app.hist_event = threading.Event()

    def hist(self, reqId: int, bar) -> None:  # noqa: N802 - IB callback
        self.historical_data.append(bar)

    def hist_end(self, reqId: int, start: str, end: str) -> None:  # noqa: N802
        self.hist_event.set()

    app.historicalData = MethodType(hist, app)
    app.historicalDataEnd = MethodType(hist_end, app)

    contract = Contract()
    contract.symbol = symbol
    contract.secType = "STK"
    contract.exchange = cfg_get("UNDERLYING_EXCHANGE", "SMART")
    contract.primaryExchange = cfg_get("UNDERLYING_PRIMARY_EXCHANGE", "ARCA")
    contract.currency = "USD"
    # Stocks are non-expiring instruments; setting includeExpired can trigger
    # HMDS validation errors. Use the default ``False`` value.
    contract.includeExpired = False

    # Use a timezone-aware timestamp in UTC. The IB API interprets a dash
    # between the date and time as UTC, so no explicit timezone string is
    # required.
    query_time = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S")
    logger.debug(contract.__dict__)
    app.reqHistoricalData(
        1,
        contract,
        query_time,
        "504 D",
        "1 day",
        "TRADES",
        0,
        1,
        False,
        [],
    )
    app.hist_event.wait(10)
    if not app.historical_data:
        logger.error(f"⚠️ Geen koersdata ontvangen voor {symbol}")
        return []

    records = [
        {
            "symbol": symbol,
            "date": _format_date(bar.date),
            "close": bar.close,
            "volume": int(bar.volume) if getattr(bar, "volume", None) is not None else None,
            "atr": None,
        }
        for bar in app.historical_data
    ]
    return records


def main(argv: List[str] | None = None) -> None:
    """Fetch price history for default or provided symbols."""
    setup_logging()
    logger.info("🚀 Price history fetch")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    app = connect_ib()
    stored = 0
    try:
        for sym in symbols:
            records = list(_request_bars(app, sym))
            if not records:
                continue
            file = base_dir / f"{sym}.json"
            for rec in records:
                update_json_file(file, rec, ["date"])
            stored += 1
    finally:
        app.disconnect()
    logger.success(f"✅ Historische prijzen opgeslagen voor {stored} symbolen")

    # Immediately compute volatility statistics for the fetched symbols
    compute_volstats_main(symbols)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
