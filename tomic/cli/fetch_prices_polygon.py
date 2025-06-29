from __future__ import annotations

"""Fetch daily price history using the Polygon API."""

from datetime import datetime, timedelta, date
from pathlib import Path
from time import sleep
from typing import Iterable, List

from tomic.analysis.metrics import average_true_range

from tomic.config import get as cfg_get
from tomic.logutils import logger, setup_logging
from tomic.journal.utils import load_json, save_json
from tomic.polygon_client import PolygonClient
from tomic.providers.polygon_iv import _load_latest_close
from .compute_volstats_polygon import main as compute_volstats_polygon_main


def _is_weekday(d: date) -> bool:
    """Return ``True`` when ``d`` falls on a weekday."""
    return d.weekday() < 5


def _next_trading_day(d: date) -> date:
    """Return the next weekday after ``d``."""
    d += timedelta(days=1)
    while not _is_weekday(d):
        d += timedelta(days=1)
    return d


def _request_bars(client: PolygonClient, symbol: str) -> Iterable[dict]:
    """Return daily bar records for ``symbol`` using Polygon.

    This function fetches only the missing dates based on the last close
    available in ``PRICE_HISTORY_DIR``. If no local data exists it falls back
    to requesting the last 252 trading days.
    """

    today = datetime.now().date()
    _, last_date = _load_latest_close(symbol)
    params = {"adjusted": "true"}
    base_path = f"v2/aggs/ticker/{symbol}/range/1/day"
    path = base_path

    end_dt = today
    while not _is_weekday(end_dt):
        end_dt -= timedelta(days=1)

    if last_date:
        try:
            last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
        except Exception:
            last_dt = end_dt - timedelta(days=365)
        next_expected = _next_trading_day(last_dt)
        if next_expected > end_dt:
            logger.info(
                f"⏭️ {symbol}: laatste data is van {last_date}, geen nieuwe werkdag beschikbaar."
            )
            return []
        from_date = next_expected.strftime("%Y-%m-%d")
        to_date = end_dt.strftime("%Y-%m-%d")
        path = f"{base_path}/{from_date}/{to_date}"
    else:
        params.update({"limit": 252, "to": end_dt.strftime("%Y-%m-%d")})

    data = client._request(path, params)
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


def _merge_price_data(file: Path, records: list[dict]) -> int:
    """Merge ``records`` into ``file`` keeping existing entries intact."""

    data = load_json(file)
    if not isinstance(data, list):
        data = []
    existing_dates = {rec.get("date") for rec in data if isinstance(rec, dict)}
    new = [r for r in records if r.get("date") not in existing_dates]
    if not new:
        return 0
    data.extend(new)
    data.sort(key=lambda r: r.get("date", ""))
    save_json(data, file)
    return len(new)


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

    base_dir = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    client = PolygonClient()
    client.connect()
    stored = 0
    processed: list[str] = []
    try:
        for idx, sym in enumerate(symbols):
            if max_syms is not None and idx >= max_syms:
                break
            logger.info(f"Fetching bars for {sym}")
            records = list(_request_bars(client, sym))
            if not records:
                logger.warning(f"No price data for {sym}")
            else:
                file = base_dir / f"{sym}.json"
                added = _merge_price_data(file, records)
                logger.info(f"{sym}: {added} nieuwe datapunten")
                if added:
                    stored += 1
            processed.append(sym)
            sleep(sleep_between)
    finally:
        client.disconnect()
    logger.success(f"✅ Historische prijzen opgeslagen voor {stored} symbolen")

    compute_volstats_polygon_main(processed)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
