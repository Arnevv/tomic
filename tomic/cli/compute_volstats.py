"""Compute daily volatility statistics and store them in the database."""

from __future__ import annotations

from datetime import datetime
from typing import List

from tomic.logutils import logger, setup_logging
from tomic.config import get as cfg_get
from tomic.analysis.vol_db import init_db, save_vol_stats, VolRecord
from tomic.analysis.metrics import historical_volatility
from tomic.api.market_client import TermStructureClient, start_app, await_market_data


def _get_closes(conn, symbol: str) -> list[float]:
    cur = conn.execute(
        "SELECT close FROM PriceHistory WHERE symbol=? ORDER BY date",
        (symbol,),
    )
    return [row[0] for row in cur.fetchall()]


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

    conn = init_db(cfg_get("VOLATILITY_DB", "data/volatility.db"))
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        for sym in symbols:
            closes = _get_closes(conn, sym)
            if not closes:
                logger.warning(f"No price history for {sym}")
                continue
            hv30 = historical_volatility(closes, window=30)
            hv60 = historical_volatility(closes, window=60)
            hv90 = historical_volatility(closes, window=90)
            iv = fetch_iv30d(sym)
            record = VolRecord(
                symbol=sym,
                date=today,
                iv=iv,
                hv30=hv30,
                hv60=hv60,
                hv90=hv90,
                iv_rank=None,
                iv_percentile=None,
            )
            save_vol_stats(conn, record, closes)
            logger.info(f"Saved vol stats for {sym}")
    finally:
        conn.close()
    logger.success("✅ Volatility stats updated")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
