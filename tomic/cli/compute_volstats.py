"""Compute daily volatility statistics and store them in the database."""

from __future__ import annotations

from datetime import datetime
from typing import List

from tomic.logutils import logger, setup_logging
from tomic.config import get as cfg_get
from pathlib import Path

from tomic.journal.utils import update_json_file
from tomic.analysis.metrics import historical_volatility
from tomic.api.market_client import TermStructureClient, start_app, await_market_data
from tomic.utils import latest_close_date, load_price_history


def _get_closes(symbol: str) -> list[float]:
    data = load_price_history(symbol)
    closes: list[float] = []
    for rec in data:
        try:
            closes.append(float(rec.get("close", 0)))
        except Exception:
            continue
    return closes


def fetch_iv30d(symbol: str) -> float | None:
    """Return approximate 30-day implied volatility for ``symbol`` using TWS."""
    app = TermStructureClient(symbol)
    start_app(app)
    try:
        if not await_market_data(app, symbol):
            return None
        if app.spot_price is None:
            return None
        ivs_by_expiry: dict[str, list[float]] = {}
        strike_window = int(cfg_get("TERM_STRIKE_WINDOW", 1))
        for req_id, rec in app.market_data.items():
            if req_id in app.invalid_contracts:
                continue
            iv = rec.get("iv")
            strike = rec.get("strike")
            expiry = rec.get("expiry")
            if iv is None or strike is None or expiry is None:
                continue
            if abs(float(strike) - float(app.spot_price)) <= strike_window:
                ivs_by_expiry.setdefault(str(expiry), []).append(float(iv))
        if not ivs_by_expiry:
            return None
        first = sorted(ivs_by_expiry.keys())[0]
        ivs = ivs_by_expiry[first]
        if not ivs:
            return None
        return sum(ivs) / len(ivs)
    finally:
        app.disconnect()


def main(argv: List[str] | None = None) -> None:
    """Compute volatility stats for configured symbols."""
    setup_logging()
    logger.info("🚀 Computing volatility stats")
    if argv is None:
        argv = []
    symbols = [s.upper() for s in argv] if argv else [s.upper() for s in cfg_get("DEFAULT_SYMBOLS", [])]

    summary_dir = Path(cfg_get("IV_DAILY_SUMMARY_DIR", "tomic/data/iv_daily_summary"))
    hv_dir = Path(cfg_get("HISTORICAL_VOLATILITY_DIR", "tomic/data/historical_volatility"))

    def rolling_hv(closes: list[float], window: int) -> list[float]:
        result = []
        for i in range(window, len(closes) + 1):
            hv = historical_volatility(closes[i - window : i], window=window)
            if hv is not None:
                result.append(hv)
        return result

    def iv_rank(iv: float, series: list[float]) -> float | None:
        if not series:
            return None
        lo = min(series)
        hi = max(series)
        if hi == lo:
            return None
        return (iv - lo) / (hi - lo)

    def iv_percentile(iv: float, series: list[float]) -> float | None:
        if not series:
            return None
        count = sum(1 for hv in series if hv < iv)
        return count / len(series)

    for sym in symbols:
        closes = _get_closes(sym)
        if not closes:
            logger.warning(f"No price history for {sym}")
            continue
        hv20 = historical_volatility(closes, window=20)
        hv30 = historical_volatility(closes, window=30)
        hv90 = historical_volatility(closes, window=90)
        hv252 = historical_volatility(closes, window=252)
        iv = fetch_iv30d(sym)
        date_str = latest_close_date(sym) or datetime.now().strftime("%Y-%m-%d")
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
            "date": date_str,
            "hv20": hv20,
            "hv30": hv30,
            "hv90": hv90,
            "hv252": hv252,
        }
        update_json_file(hv_dir / f"{sym}.json", hv_record, ["date"])

        summary_record = {
            "date": date_str,
            "atm_iv": iv,
            "iv_rank": rank,
            "iv_percentile": pct,
        }
        update_json_file(summary_dir / f"{sym}.json", summary_record, ["date"])
        logger.info(f"Saved vol stats for {sym}")
    logger.success("✅ Volatility stats updated")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
