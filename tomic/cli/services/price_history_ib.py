from __future__ import annotations

"""Services for fetching daily price history via Interactive Brokers."""

import threading
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from typing import Iterable, Sequence

from ibapi.contract import Contract

from tomic.api.ib_connection import connect_ib
from tomic.config import get as cfg_get
from tomic.journal.utils import update_json_file
from tomic.logutils import logger

from .volatility import compute_volatility_stats


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


def fetch_ib_daily_prices(symbols: Sequence[str] | None = None, *, compute_volstats: bool = True) -> list[str]:
    """Fetch price history for ``symbols`` (defaults to configuration)."""
    configured = cfg_get("DEFAULT_SYMBOLS", [])
    target_symbols = [s.upper() for s in symbols] if symbols else [s.upper() for s in configured]
    if not target_symbols:
        logger.warning("No symbols configured for IB price fetch")
        return []

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    app = connect_ib()
    stored: list[str] = []
    try:
        for sym in target_symbols:
            records = list(_request_bars(app, sym))
            if not records:
                continue
            file = base_dir / f"{sym}.json"
            for rec in records:
                update_json_file(file, rec, ["date"])
            stored.append(sym)
    finally:
        app.disconnect()

    if stored:
        logger.success(f"✅ Historische prijzen opgeslagen voor {len(stored)} symbolen")
    else:
        logger.warning("⚠️ Geen historische prijzen opgeslagen")

    if compute_volstats and stored:
        compute_volatility_stats(stored)
    return stored
