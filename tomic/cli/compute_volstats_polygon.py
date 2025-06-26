from __future__ import annotations

"""Compute daily volatility statistics using Polygon IV data."""

from datetime import datetime
from pathlib import Path
from time import sleep
from typing import List

from tomic.analysis.metrics import historical_volatility
from tomic.config import get as cfg_get
from tomic.journal.utils import load_json, update_json_file
from tomic.logutils import logger, setup_logging
from tomic.providers.polygon_iv import fetch_polygon_iv30d


def _get_closes(symbol: str) -> list[float]:
    """Return list of close prices for ``symbol`` sorted by date."""
    base = Path(cfg_get("PRICE_HISTORY_DIR", "tomic/data/spot_prices"))
    path = base / f"{symbol}.json"
    data = load_json(path)
    if not isinstance(data, list):
        return []
    data.sort(key=lambda r: r.get("date", ""))
    return [float(rec.get("close", 0)) for rec in data]


def main(argv: List[str] | None = None) -> None:
    """Compute volatility stats for provided or default symbols."""
    setup_logging()
    logger.info("🚀 Computing volatility stats (Polygon)")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))
    today = datetime.now().strftime("%Y-%m-%d")

    def rolling_hv(closes: list[float], window: int) -> list[float]:
        result = []
        for i in range(window, len(closes) + 1):
            hv = historical_volatility(closes[i - window : i], window=window)
            if hv is not None:
                result.append(hv)
        return result

    def iv_rank(value: float, series: list[float]) -> float | None:
        if not series:
            return None
        lo = min(series)
        hi = max(series)
        if hi == lo:
            return None
        return (value - lo) / (hi - lo) * 100

    def iv_percentile(value: float, series: list[float]) -> float | None:
        if not series:
            return None
        count = sum(1 for hv in series if hv < value)
        return count / len(series) * 100

    for idx, sym in enumerate(symbols):
        closes = _get_closes(sym)
        if not closes:
            logger.warning(f"No price history for {sym}")
            continue
        hv20 = historical_volatility(closes, window=20)
        hv30 = historical_volatility(closes, window=30)
        hv90 = historical_volatility(closes, window=90)
        hv252 = historical_volatility(closes, window=252)
        iv = fetch_polygon_iv30d(sym)
        if iv is None:
            logger.warning(f"No implied volatility for {sym}")
        hv_series = rolling_hv(closes, 30)
        scaled_iv = iv * 100 if iv is not None else None
        rank = iv_rank(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None
        pct = iv_percentile(scaled_iv or 0.0, hv_series) if scaled_iv is not None else None

        if hv20 is not None:
            hv20 /= 100
        if hv30 is not None:
            hv30 /= 100
        if hv90 is not None:
            hv90 /= 100
        if hv252 is not None:
            hv252 /= 100

        hv_record = {
            "date": today,
            "hv20": hv20,
            "hv30": hv30,
            "hv90": hv90,
            "hv252": hv252,
        }
        update_json_file(hv_dir / f"{sym}.json", hv_record, ["date"])

        summary_record = {
            "date": today,
            "atm_iv": iv,
            "iv_rank (HV)": rank,
            "iv_percentile (HV)": pct,
        }
        update_json_file(summary_dir / f"{sym}.json", summary_record, ["date"])
        logger.info(f"Saved vol stats for {sym}")
        if idx < len(symbols) - 1:
            logger.info("Throttling for 13 seconds to respect rate limits")
            sleep(13)
    logger.success("✅ Volatility stats updated")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
