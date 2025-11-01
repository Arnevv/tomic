from __future__ import annotations

"""Utility functions for retrieving and storing price history via Polygon."""

from datetime import datetime, timedelta, date, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from typing import Mapping

try:  # pragma: no cover - optional dependency
    import holidays  # type: ignore
except Exception:  # pragma: no cover - fallback when package is missing
    class _NoHolidays:
        def __contains__(self, _date: date) -> bool:
            return False

    holidays = SimpleNamespace(  # type: ignore
        US=lambda: _NoHolidays(), NYSE=lambda: _NoHolidays()
    )

from tomic.analysis.metrics import average_true_range
from tomic.config import get as cfg_get
from tomic.logutils import logger
from tomic.infrastructure.storage import (
    load_json,
    save_json,
    merge_json_records,
)
from tomic.helpers.price_utils import _load_latest_close
from tomic.helpers.price_meta import load_price_meta
from tomic.integrations.polygon.client import PolygonClient


_US_MARKET_HOLIDAYS = None


def _is_weekday(d: date) -> bool:
    """Return ``True`` when ``d`` falls on a weekday."""
    return d.weekday() < 5


def _us_market_holidays():
    """Return a holiday calendar for US equity markets."""

    global _US_MARKET_HOLIDAYS
    if _US_MARKET_HOLIDAYS is None:
        try:
            calendar_factory = getattr(holidays, "NYSE")
        except AttributeError:  # pragma: no cover - NYSE calendar missing
            calendar_factory = getattr(holidays, "US")
        _US_MARKET_HOLIDAYS = calendar_factory()
    return _US_MARKET_HOLIDAYS


def _next_trading_day(d: date) -> date:
    """Return the next US trading day after ``d``."""

    us_holidays = _us_market_holidays()
    d += timedelta(days=1)
    while not _is_weekday(d) or d in us_holidays:
        d += timedelta(days=1)
    return d


def latest_trading_day() -> date:
    """Return the most recent US trading day."""

    tz = ZoneInfo("America/New_York")
    now = datetime.now(tz)
    d = now.date() - timedelta(days=1)
    us_holidays = _us_market_holidays()
    while d.weekday() >= 5 or d in us_holidays:
        d -= timedelta(days=1)
    return d


def request_bars(client: PolygonClient, symbol: str) -> tuple[list[dict], bool]:
    """Return daily bar records for ``symbol`` and whether a request was made."""
    end_dt = latest_trading_day()
    _, last_date = _load_latest_close(symbol)
    meta = load_price_meta()
    meta_entry = meta.get(symbol)
    ts_str = None
    if isinstance(meta_entry, Mapping):
        ts_str = (
            meta_entry.get("fetched_at")
            or meta_entry.get("timestamp")
            or meta_entry.get("last_fetch")
        )
    elif isinstance(meta_entry, str):
        ts_str = meta_entry
    if last_date and ts_str:
        try:
            tz = ZoneInfo("America/New_York")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz)
            else:
                ts = ts.astimezone(tz)
            if (
                ts.date() == datetime.strptime(last_date, "%Y-%m-%d").date()
                and ts.time() < dt_time(16, 0)
            ):
                base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
                file = base / f"{symbol}.json"
                data = load_json(file)
                if isinstance(data, list):
                    data = [r for r in data if r.get("date") != last_date]
                    save_json(data, file)
                _, last_date = _load_latest_close(symbol)
        except Exception:
            pass
    params = {"adjusted": "true"}
    base_path = f"v2/aggs/ticker/{symbol}/range/1/day"
    path = base_path
    requested = False

    lookback_years = cfg_get("PRICE_HISTORY_LOOKBACK_YEARS", 2)
    try:
        lookback_years = int(lookback_years)
    except (TypeError, ValueError):  # pragma: no cover - invalid config override
        lookback_years = 2
    lookback_years = max(1, lookback_years)

    if last_date:
        try:
            last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
        except Exception:
            last_dt = end_dt - timedelta(days=lookback_years * 365)
        next_expected = _next_trading_day(last_dt)
        if next_expected > end_dt:
            logger.info(
                (
                    "⏭️ %s: laatste data is van %s; "
                    "volgende handelsdag %s valt na %s, niets te doen."
                ),
                symbol,
                last_date,
                next_expected,
                end_dt,
            )
            return [], requested
        from_date = next_expected.strftime("%Y-%m-%d")
        to_date = end_dt.strftime("%Y-%m-%d")
        path = f"{base_path}/{from_date}/{to_date}"
    else:
        to_date = end_dt.strftime("%Y-%m-%d")
        from_date = (end_dt - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")
        path = f"{base_path}/{from_date}/{to_date}"
        approx_trading_days = min(50000, max(lookback_years * 252, 1))
        params.update({"limit": approx_trading_days})

    requested = True
    logger.info(f"Fetching bars for {symbol}")
    try:
        data = client._request(path, params)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 403:
            logger.warning(f"⚠️ Skipping {symbol} — all keys rejected with 403")
            return [], requested
        raise
    bars = data.get("results") or []
    records: list[dict] = []
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
    return records, requested


def merge_price_data(file: Path, records: list[dict]) -> int:
    """Merge ``records`` into ``file`` keeping existing entries intact."""

    return merge_json_records(file, records, key="date")


